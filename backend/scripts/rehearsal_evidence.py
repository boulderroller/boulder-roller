"""Fail-closed, atomic evidence for the isolated V4-B rehearsal command."""

from __future__ import annotations

import asyncio
import contextlib
import errno
import fcntl
import hashlib
import json
import os
import struct
import tempfile
import threading
from pathlib import Path
from typing import Any, Sequence

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.address_lookup_table_account import (
    AddressLookupTable,
    AddressLookupTableAccount,
    ID as ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    derive_lookup_table_address,
)
from solders.hash import Hash
from solders.pubkey import Pubkey
from solders.signature import Signature

from app.solana_direct import (
    TOKEN_PROGRAM_ID,
    _account_data_bytes,
    _derive_ata,
    _derive_cal_mint_receipt_pda,
    _derive_climb_completion_receipt_pda,
    _derive_dung_mint_state_pda,
    _derive_local_legend_pda,
    _derive_program_config_pda,
    _derive_ride_attestation_pda,
    _derive_ride_tribute_budget_pda,
    _derive_rider_soul_pda,
    _derive_vault_activation_pda,
    _derive_vault_cal_escrow_pda,
    _derive_vault_completion_pda,
    _derive_vault_counter_pda,
    _derive_vault_leaderboard_pda,
    _derive_vault_lp_mint_pda,
    _derive_vault_pda,
    _derive_vault_position_lp_pda,
    _derive_vault_stake_pda,
    _discriminator,
    _get_boulder_accounts_coder,
    derive_vault_pot_address,
    parse_vault_counter,
)
from app.solana_env import (
    DEFAULT_BOULDER_ROLLERS_PROGRAM_ID,
    DEFAULT_CAL_MINT_ADDRESS,
    DEFAULT_DUNG_MINT_ADDRESS,
)
from app.services.solana_submit import is_blockhash_valid_compat


EVIDENCE_SCHEMA = "boulderroller_v4b_rehearsal_evidence_v2"
BPF_UPGRADEABLE_LOADER_ID = Pubkey.from_string(
    "BPFLoaderUpgradeab1e11111111111111111111111"
)
PROTECTED_PROGRAM_ID = Pubkey.from_string(str(DEFAULT_BOULDER_ROLLERS_PROGRAM_ID))
PROTECTED_TEST_USDC_MINT = Pubkey.from_string(
    "DpLPBaRuLnBsR3P3meU1tmiNUxreXwskXBebTYKvNGne"
)
PROTECTED_CANONICAL_USDC_TREASURY = Pubkey.from_string(
    "GEL1JhavEKPuqVBvUiezUgNG2VYK1jtzsUazo2Scm1jA"
)
PROTECTED_SHAWMONT_CLIMB = Pubkey.from_string(
    "2rMLaYSEN7SJBvjZQ72CS1RfSM3LwDd6Ru3isJjUxKRD"
)


def _field_value(fields: dict[str, Any], *names: str, default: Any = None) -> Any:
    for name in names:
        if name in fields:
            return fields[name]
    return default


def _decoded_fields(evidence: dict[str, Any]) -> dict[str, Any]:
    decoded = evidence.get("decoded") or {}
    fields = decoded.get("fields") or {}
    return fields if isinstance(fields, dict) else {}


def _pubkey_value(value: object, label: str) -> Pubkey:
    try:
        result = Pubkey.from_string(str(value))
    except Exception as exc:
        raise RuntimeError(f"{label} is not a valid public key") from exc
    if result == Pubkey.default():
        raise RuntimeError(f"{label} is not configured")
    return result


def _atomic_write(path: Path, payload: dict[str, Any]) -> None:
    if not path.is_absolute():
        raise RuntimeError("--rehearsal-evidence must be an absolute path")
    if not path.parent.is_dir():
        raise RuntimeError(
            f"rehearsal evidence parent directory does not exist: {path.parent}"
        )
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
def _exclusive_manifest_lock(path: Path):
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


def _json_value(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Pubkey):
        return str(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if hasattr(value, "__dict__"):
        return _json_value(vars(value))
    return str(value)


def _instruction_names() -> dict[str, str]:
    names = (
        "record_ride",
        "credit_cal",
        "create_vault_with_usdc",
        "configure_usdc_payment",
        "admin_override_open_settlement_week",
        "admin_seed_pending_rewards",
        "record_climb_completion_v2",
        "stake_cal_in_vault",
        "admin_override_stake_eligibility",
        "distribute_epoch_rewards",
        "collect_stake_rewards_for",
        "unstake_cal_from_vault",
        "harvest_rewards",
    )
    return {_discriminator(name).hex(): name for name in names}


INSTRUCTION_NAMES = _instruction_names()


class RehearsalEvidenceManifest:
    """Durable baseline, pre-submit protection, and finalized reconciliation."""

    def __init__(
        self,
        *,
        path: Path,
        rpc_url: str,
        state: dict[str, Any],
    ) -> None:
        self.path = path.resolve()
        self.rpc_url = rpc_url
        self._state = state
        self._lock = threading.RLock()
        self._run_lock_descriptor: int | None = None

    @classmethod
    async def open(
        cls,
        *,
        path: Path,
        rpc_url: str,
        program_id: Pubkey,
        cal_mint: Pubkey,
        dung_mint: Pubkey,
        user: Pubkey,
        climb_pda: Pubkey | None,
        existing_vault_id: int | None,
        settlement_week: int | None,
        usdc_mint: Pubkey,
        usdc_treasury: Pubkey,
        transport_state_path: Path,
        vault_creation_cal: int = 0,
        vault_creation_usdc: int = 0,
        harvest_fee_bps: int = 0,
        user_cal: int = 0,
        stake_cal: int = 0,
        vault_alloc_cal: int = 0,
        setup_evidence_path: Path | None = None,
        setup_evidence_sha256: str | None = None,
        initial_usdc_supply: int = 0,
    ) -> "RehearsalEvidenceManifest":
        if not path.is_absolute():
            raise RuntimeError("--rehearsal-evidence must be an absolute path")
        resolved = path.resolve()
        existing: dict[str, Any] | None = None
        if resolved.exists():
            try:
                loaded = json.loads(resolved.read_text(encoding="utf-8"))
            except Exception as exc:
                raise RuntimeError("rehearsal evidence artifact is unreadable") from exc
            if not isinstance(loaded, dict) or loaded.get("schema") != EVIDENCE_SCHEMA:
                raise RuntimeError("rehearsal evidence schema does not match")
            existing = loaded

        if existing is None and existing_vault_id is not None:
            raise RuntimeError(
                "--existing-vault-id requires its exact existing rehearsal evidence artifact"
            )

        if existing is not None:
            stored_identity = existing.get("identity") or {}
            if climb_pda is None:
                climb_pda = Pubkey.from_string(str(stored_identity.get("climb_pda")))
            stored_vault_id = int(stored_identity.get("vault_id"))
            if existing_vault_id is not None and existing_vault_id != stored_vault_id:
                raise RuntimeError("resume Vault ID does not match rehearsal evidence")
            if existing_vault_id is None and any(
                tx.get("stage") == "create_vault_with_usdc"
                and tx.get("status") in {"prepared", "confirmed", "finalized"}
                for tx in existing.get("transactions", [])
            ):
                raise RuntimeError(
                    "rehearsal evidence already persisted a Vault creation attempt; "
                    "resume with "
                    f"--existing-vault-id {stored_vault_id} and its Settlement Week"
                )
            stored_week = stored_identity.get("settlement_week")
            if (
                settlement_week is not None
                and stored_week is not None
                and settlement_week != int(stored_week)
            ):
                raise RuntimeError(
                    "resume Settlement Week does not match rehearsal evidence"
                )
            vault_id = stored_vault_id
        else:
            if climb_pda is None:
                raise RuntimeError(
                    "new rehearsal evidence requires the exact registered Climb"
                )
            vault_id = (
                existing_vault_id
                if existing_vault_id is not None
                else await cls._read_rehearsal_counter(
                    rpc_url=rpc_url,
                    program_id=program_id,
                )
            )

        expected_vault, _ = _derive_vault_pda(vault_id, program_id)
        protected_addresses = await cls._resolve_protected_addresses(rpc_url)
        rehearsal_addresses = await cls._resolve_rehearsal_addresses(
            rpc_url=rpc_url,
            program_id=program_id,
            cal_mint=cal_mint,
            dung_mint=dung_mint,
            usdc_mint=usdc_mint,
            usdc_treasury=usdc_treasury,
            user=user,
            climb_pda=climb_pda,
            vault_id=vault_id,
            expected_vault=expected_vault,
        )
        protected_by_address = {
            str(address): label for label, address in protected_addresses.items()
        }
        overlap = [
            f"{label}={address} ({protected_by_address[str(address)]})"
            for label, address in rehearsal_addresses.items()
            if str(address) in protected_by_address
        ]
        if overlap:
            raise RuntimeError(
                "rehearsal identity overlaps protected canonical account: "
                + ", ".join(overlap)
            )
        slot, protected = await cls._read_accounts(
            rpc_url,
            protected_addresses,
        )
        rehearsal_slot, rehearsal = await cls._read_accounts(
            rpc_url,
            rehearsal_addresses,
        )

        identity = {
            "program_id": str(program_id),
            "cal_mint": str(cal_mint),
            "dung_mint": str(dung_mint),
            "usdc_mint": str(usdc_mint),
            "usdc_treasury": str(usdc_treasury),
            "user": str(user),
            "climb_pda": str(climb_pda),
            "vault_id": vault_id,
            "expected_vault": str(expected_vault),
            "settlement_week": (
                int(existing["identity"]["settlement_week"])
                if existing is not None
                and existing["identity"].get("settlement_week") is not None
                else settlement_week
            ),
            "transport_state_path": str(transport_state_path.resolve()),
            "vault_creation_cal": int(vault_creation_cal),
            "vault_creation_cal_base_units": int(vault_creation_cal) * 1_000_000_000,
            "vault_creation_usdc": int(vault_creation_usdc),
            "harvest_fee_bps": int(harvest_fee_bps),
            "user_cal": int(user_cal),
            "stake_cal": int(stake_cal),
            "vault_alloc_cal": int(vault_alloc_cal),
            "setup_evidence_path": (
                str(setup_evidence_path.resolve())
                if setup_evidence_path is not None
                else None
            ),
            "setup_evidence_sha256": setup_evidence_sha256,
            "initial_usdc_supply": int(initial_usdc_supply),
        }
        if existing is None:
            cls._require_baseline_accounts(protected, rehearsal, fresh=existing_vault_id is None)
            cls._validate_rehearsal_authorities(rehearsal, identity)
            state = {
                "schema": EVIDENCE_SCHEMA,
                "identity": identity,
                "protected_addresses": {
                    label: str(address) for label, address in protected_addresses.items()
                },
                "rehearsal_addresses": {
                    label: str(address) for label, address in rehearsal_addresses.items()
                },
                "dynamic_rehearsal_addresses": {},
                "baseline": {
                    "protected_slot": slot,
                    "rehearsal_slot": rehearsal_slot,
                    "protected": protected,
                    "rehearsal": rehearsal,
                },
                "transactions": [],
                "reconciliations": [],
            }
            with _exclusive_manifest_lock(resolved):
                if resolved.exists():
                    raise RuntimeError(
                        "rehearsal evidence appeared during baseline capture; retry "
                        "with its exact resume identity"
                    )
                _atomic_write(resolved, state)
        else:
            if existing.get("identity") != identity:
                raise RuntimeError("rehearsal evidence identity does not match this command")
            cls._assert_protected_baseline(
                existing.get("baseline", {}).get("protected", {}),
                protected,
            )
            cls._require_baseline_accounts(
                protected,
                rehearsal,
                fresh=existing_vault_id is None,
            )
            cls._validate_rehearsal_authorities(rehearsal, identity)
            state = existing
        return cls(path=resolved, rpc_url=rpc_url, state=state)

    @staticmethod
    async def _read_rehearsal_counter(*, rpc_url: str, program_id: Pubkey) -> int:
        counter_address, _ = _derive_vault_counter_pda(program_id)
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_account_info(
                counter_address,
                commitment=Finalized,
            )
        if response.value is None or response.value.owner != program_id:
            raise RuntimeError("rehearsal VaultCounter is unavailable")
        counter = parse_vault_counter(_account_data_bytes(response.value.data))
        if counter is None:
            raise RuntimeError("rehearsal VaultCounter failed exact decoding")
        return counter.count

    @staticmethod
    def _protected_addresses_from_config(
        *,
        program_data: Pubkey,
        program_config: dict[str, Any],
        vault_actors: Sequence[Pubkey] = (),
    ) -> dict[str, Pubkey]:
        """Freeze every canonical identity that the rehearsal flow could move."""
        cal_mint = _pubkey_value(program_config.get("cal_mint"), "canonical CAL mint")
        dung_mint = _pubkey_value(
            program_config.get("dung_mint"), "canonical DUNG mint"
        )
        configured_usdc = _pubkey_value(
            program_config.get("usdc_mint"), "canonical USDC mint"
        )
        if cal_mint != Pubkey.from_string(str(DEFAULT_CAL_MINT_ADDRESS)):
            raise RuntimeError("canonical ProgramConfig CAL mint changed")
        if dung_mint != Pubkey.from_string(str(DEFAULT_DUNG_MINT_ADDRESS)):
            raise RuntimeError("canonical ProgramConfig DUNG mint changed")
        if configured_usdc != PROTECTED_TEST_USDC_MINT:
            raise RuntimeError("canonical ProgramConfig test-USDC mint changed")

        config, _ = _derive_program_config_pda(PROTECTED_PROGRAM_ID)
        counter, _ = _derive_vault_counter_pda(PROTECTED_PROGRAM_ID)
        dung_state, _ = _derive_dung_mint_state_pda(PROTECTED_PROGRAM_ID)
        vault, _ = _derive_vault_pda(0, PROTECTED_PROGRAM_ID)
        activation, _ = _derive_vault_activation_pda(0, PROTECTED_PROGRAM_ID)
        record_board, _ = _derive_vault_leaderboard_pda(0, PROTECTED_PROGRAM_ID)
        local_legend, _ = _derive_local_legend_pda(0, PROTECTED_PROGRAM_ID)
        lp_mint, _ = _derive_vault_lp_mint_pda(0, PROTECTED_PROGRAM_ID)
        cal_escrow, _ = _derive_vault_cal_escrow_pda(0, PROTECTED_PROGRAM_ID)
        usdc_treasury = _pubkey_value(
            program_config.get("usdc_treasury_token_account"),
            "canonical USDC treasury",
        )
        if usdc_treasury != PROTECTED_CANONICAL_USDC_TREASURY:
            raise RuntimeError("canonical ProgramConfig USDC treasury changed")
        addresses = {
            "protected_program": PROTECTED_PROGRAM_ID,
            "protected_program_data": program_data,
            "protected_program_config": config,
            "protected_vault_counter": counter,
            "protected_dung_mint_state": dung_state,
            "protected_cal_mint": cal_mint,
            "protected_dung_mint": dung_mint,
            "protected_test_usdc_mint": PROTECTED_TEST_USDC_MINT,
            "protected_configured_usdc_mint": configured_usdc,
            "protected_usdc_treasury": usdc_treasury,
            "protected_dung_pol": _pubkey_value(
                program_config.get("pol_token_account"), "canonical DUNG POL"
            ),
            "protected_dung_treasury": _pubkey_value(
                program_config.get("treasury_token_account"),
                "canonical DUNG treasury",
            ),
            "protected_shawmont_climb": PROTECTED_SHAWMONT_CLIMB,
            "protected_shawmont_vault_0": vault,
            "protected_shawmont_activation": activation,
            "protected_shawmont_record_board": record_board,
            "protected_shawmont_local_legend": local_legend,
            "protected_shawmont_lp_mint": lp_mint,
            "protected_shawmont_cal_escrow": cal_escrow,
            "protected_shawmont_dung_pot": derive_vault_pot_address(
                0, PROTECTED_PROGRAM_ID, dung_mint
            ),
        }
        seen: set[str] = set()
        for index, actor in enumerate(vault_actors):
            if actor == Pubkey.default() or str(actor) in seen:
                continue
            seen.add(str(actor))
            stake, _ = _derive_vault_stake_pda(actor, 0, PROTECTED_PROGRAM_ID)
            position, _ = _derive_vault_position_lp_pda(
                actor, 0, PROTECTED_PROGRAM_ID
            )
            addresses[f"protected_shawmont_actor_{index}_stake"] = stake
            addresses[f"protected_shawmont_actor_{index}_position_lp"] = position
            addresses[f"protected_shawmont_actor_{index}_cal_ata"] = _derive_ata(
                actor, cal_mint
            )
            addresses[f"protected_shawmont_actor_{index}_dung_ata"] = _derive_ata(
                actor, dung_mint
            )
            addresses[f"protected_shawmont_actor_{index}_usdc_ata"] = _derive_ata(
                actor, configured_usdc
            )
        return addresses

    @classmethod
    async def _resolve_protected_addresses(
        cls, rpc_url: str
    ) -> dict[str, Pubkey]:
        config, _ = _derive_program_config_pda(PROTECTED_PROGRAM_ID)
        vault, _ = _derive_vault_pda(0, PROTECTED_PROGRAM_ID)
        legend, _ = _derive_local_legend_pda(0, PROTECTED_PROGRAM_ID)
        board, _ = _derive_vault_leaderboard_pda(0, PROTECTED_PROGRAM_ID)
        discovery = {
            "protected_program": PROTECTED_PROGRAM_ID,
            "protected_program_config": config,
            "protected_shawmont_vault_0": vault,
            "protected_shawmont_local_legend": legend,
            "protected_shawmont_record_board": board,
        }
        _, snapshot = await cls._read_accounts(rpc_url, discovery)
        for label in ("protected_program", "protected_program_config"):
            if not snapshot[label]["exists"]:
                raise RuntimeError(f"canonical protection discovery is missing {label}")
        program_decoded = snapshot["protected_program"].get("decoded") or {}
        program_data = _pubkey_value(
            program_decoded.get("program_data_address"),
            "canonical ProgramData",
        )
        config_fields = _decoded_fields(snapshot["protected_program_config"])
        actors: list[Pubkey] = []
        for label, field_names in (
            ("protected_shawmont_vault_0", ("minter",)),
            ("protected_shawmont_local_legend", ("holder",)),
        ):
            fields = _decoded_fields(snapshot[label])
            raw = _field_value(fields, *field_names)
            if raw not in (None, str(Pubkey.default()), Pubkey.default()):
                actors.append(_pubkey_value(raw, f"{label} actor"))
        board_fields = _decoded_fields(snapshot["protected_shawmont_record_board"])
        for entry in _field_value(board_fields, "entries", default=()) or ():
            if isinstance(entry, dict):
                raw_user = _field_value(entry, "user")
            else:
                raw_user = getattr(entry, "user", None)
            if raw_user not in (None, str(Pubkey.default()), Pubkey.default()):
                actors.append(_pubkey_value(raw_user, "canonical Record Board rider"))

        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_program_accounts(
                PROTECTED_PROGRAM_ID,
                commitment=Finalized,
                encoding="base64",
            )
        if not hasattr(response, "value") or response.value is None:
            raise RuntimeError("canonical VaultStake inventory query failed")
        for keyed in response.value:
            account = keyed.account
            if account.owner != PROTECTED_PROGRAM_ID:
                raise RuntimeError("canonical program-account inventory owner mismatch")
            try:
                parsed = _get_boulder_accounts_coder().parse(
                    _account_data_bytes(account.data)
                )
            except Exception:
                continue
            if parsed.name != "VaultStake":
                continue
            fields = vars(parsed.data)
            if int(_field_value(fields, "vault_id", "vaultId", default=-1)) != 0:
                continue
            actors.append(
                _pubkey_value(
                    _field_value(fields, "user"),
                    f"canonical VaultStake {keyed.pubkey} rider",
                )
            )
        addresses = cls._protected_addresses_from_config(
            program_data=program_data,
            program_config=config_fields,
            vault_actors=actors,
        )
        _, full = await cls._read_accounts(rpc_url, addresses)
        cls._validate_protected_authorities(full)
        return addresses

    @staticmethod
    def _validate_protected_authorities(
        snapshot: dict[str, dict[str, Any]],
    ) -> None:
        required = {
            "protected_program": BPF_UPGRADEABLE_LOADER_ID,
            "protected_program_data": BPF_UPGRADEABLE_LOADER_ID,
            "protected_program_config": PROTECTED_PROGRAM_ID,
            "protected_vault_counter": PROTECTED_PROGRAM_ID,
            "protected_dung_mint_state": PROTECTED_PROGRAM_ID,
            "protected_cal_mint": TOKEN_PROGRAM_ID,
            "protected_dung_mint": TOKEN_PROGRAM_ID,
            "protected_test_usdc_mint": TOKEN_PROGRAM_ID,
            "protected_usdc_treasury": TOKEN_PROGRAM_ID,
            "protected_dung_pol": TOKEN_PROGRAM_ID,
            "protected_dung_treasury": TOKEN_PROGRAM_ID,
            "protected_shawmont_climb": PROTECTED_PROGRAM_ID,
        }
        failures = [
            label
            for label, owner in required.items()
            if not snapshot.get(label, {}).get("exists")
            or snapshot[label].get("owner") != str(owner)
        ]
        if failures:
            raise RuntimeError(
                "canonical protected account ownership failed: "
                + ", ".join(failures)
            )
        program_data_address = snapshot["protected_program_data"]["address"]
        if (
            not snapshot["protected_program"].get("executable")
            or (snapshot["protected_program"].get("decoded") or {}).get(
                "loader_state"
            )
            != "Program"
            or (snapshot["protected_program"].get("decoded") or {}).get(
                "program_data_address"
            )
            != program_data_address
            or (snapshot["protected_program_data"].get("decoded") or {}).get(
                "loader_state"
            )
            != "ProgramData"
        ):
            raise RuntimeError("canonical Program/ProgramData link changed")
        for label, account_type in (
            ("protected_program_config", "ProgramConfig"),
            ("protected_dung_mint_state", "DungMintState"),
        ):
            if (snapshot[label].get("decoded") or {}).get(
                "account_type"
            ) != account_type:
                raise RuntimeError(f"{label} canonical account type changed")
        if "count" not in (snapshot["protected_vault_counter"].get("decoded") or {}):
            raise RuntimeError("canonical VaultCounter failed exact decoding")
        for label in (
            "protected_cal_mint",
            "protected_dung_mint",
            "protected_test_usdc_mint",
        ):
            if "supply_base_units" not in (snapshot[label].get("decoded") or {}):
                raise RuntimeError(f"{label} failed classic SPL Mint decoding")
        dung_mint = str(DEFAULT_DUNG_MINT_ADDRESS)
        cal_mint = str(DEFAULT_CAL_MINT_ADDRESS)
        usdc_mint = str(PROTECTED_TEST_USDC_MINT)
        for label, expected_mint in (
            ("protected_dung_pol", dung_mint),
            ("protected_dung_treasury", dung_mint),
            ("protected_usdc_treasury", usdc_mint),
        ):
            fields = snapshot[label].get("decoded") or {}
            if fields.get("mint") != expected_mint:
                raise RuntimeError(f"{label} mint authority changed")
        expected_anchor_types = {
            "protected_shawmont_climb": "Climb",
            "protected_shawmont_vault_0": "Vault",
            "protected_shawmont_activation": "VaultActivation",
            "protected_shawmont_record_board": "VaultLeaderboard",
            "protected_shawmont_local_legend": "LocalLegend",
        }
        for label, account_type in expected_anchor_types.items():
            item = snapshot.get(label) or {}
            if not item.get("exists"):
                continue
            if (
                item.get("owner") != str(PROTECTED_PROGRAM_ID)
                or (item.get("decoded") or {}).get("account_type") != account_type
            ):
                raise RuntimeError(f"{label} canonical account type/owner changed")

        vault_address = snapshot.get("protected_shawmont_vault_0", {}).get(
            "address"
        )
        lp_address = snapshot.get("protected_shawmont_lp_mint", {}).get("address")
        for label, expected_mint, expected_owner in (
            ("protected_shawmont_cal_escrow", cal_mint, vault_address),
            ("protected_shawmont_dung_pot", dung_mint, vault_address),
        ):
            item = snapshot.get(label) or {}
            if not item.get("exists"):
                continue
            decoded = item.get("decoded") or {}
            if (
                item.get("owner") != str(TOKEN_PROGRAM_ID)
                or decoded.get("mint") != expected_mint
                or decoded.get("token_owner") != expected_owner
                or decoded.get("state") not in (1, 2)
            ):
                raise RuntimeError(f"{label} canonical token authority changed")
        lp = snapshot.get("protected_shawmont_lp_mint") or {}
        if lp.get("exists"):
            decoded = lp.get("decoded") or {}
            if (
                lp.get("owner") != str(TOKEN_PROGRAM_ID)
                or decoded.get("mint_authority") != vault_address
                or decoded.get("freeze_authority") != vault_address
            ):
                raise RuntimeError("canonical Shawmont LP mint authority changed")

        stake_labels = sorted(
            label
            for label in snapshot
            if label.startswith("protected_shawmont_actor_")
            and label.endswith("_stake")
        )
        for stake_label in stake_labels:
            stake_item = snapshot[stake_label]
            if not stake_item.get("exists"):
                continue
            fields = _decoded_fields(stake_item)
            rider = str(_field_value(fields, "user"))
            if (
                (stake_item.get("decoded") or {}).get("account_type")
                != "VaultStake"
                or int(_field_value(fields, "vault_id", "vaultId", default=-1))
                != 0
                or rider in {"None", str(Pubkey.default())}
            ):
                raise RuntimeError(f"{stake_label} canonical stake identity changed")
            prefix = stake_label[: -len("_stake")]
            expected = (
                (f"{prefix}_position_lp", lp_address, stake_item["address"]),
                (f"{prefix}_cal_ata", cal_mint, rider),
                (f"{prefix}_dung_ata", dung_mint, rider),
                (f"{prefix}_usdc_ata", usdc_mint, rider),
            )
            for label, expected_mint, expected_owner in expected:
                item = snapshot.get(label) or {}
                if not item.get("exists"):
                    continue
                decoded = item.get("decoded") or {}
                if (
                    item.get("owner") != str(TOKEN_PROGRAM_ID)
                    or decoded.get("mint") != expected_mint
                    or decoded.get("token_owner") != expected_owner
                    or decoded.get("state") not in (1, 2)
                ):
                    raise RuntimeError(f"{label} canonical token authority changed")
        for label, item in snapshot.items():
            if not item.get("exists") or not label.startswith("protected_shawmont_"):
                continue
            if label.endswith("_stake"):
                if (
                    item.get("owner") != str(PROTECTED_PROGRAM_ID)
                    or (item.get("decoded") or {}).get("account_type") != "VaultStake"
                ):
                    raise RuntimeError(f"{label} canonical stake type/owner changed")
            elif any(
                marker in label
                for marker in (
                    "lp_mint",
                    "cal_escrow",
                    "dung_pot",
                    "position_lp",
                    "cal_ata",
                    "dung_ata",
                    "usdc_ata",
                )
            ):
                if item.get("owner") != str(TOKEN_PROGRAM_ID):
                    raise RuntimeError(f"{label} is not owned by classic SPL Token")

    @staticmethod
    def _rehearsal_addresses(
        *,
        program_id: Pubkey,
        cal_mint: Pubkey,
        dung_mint: Pubkey,
        usdc_mint: Pubkey,
        usdc_treasury: Pubkey,
        user: Pubkey,
        climb_pda: Pubkey,
        vault_id: int,
        expected_vault: Pubkey,
        program_data: Pubkey | None = None,
        pol_account: Pubkey | None = None,
        dung_treasury: Pubkey | None = None,
    ) -> dict[str, Pubkey]:
        config, _ = _derive_program_config_pda(program_id)
        counter, _ = _derive_vault_counter_pda(program_id)
        dung_state, _ = _derive_dung_mint_state_pda(program_id)
        activation, _ = _derive_vault_activation_pda(vault_id, program_id)
        board, _ = _derive_vault_leaderboard_pda(vault_id, program_id)
        legend, _ = _derive_local_legend_pda(vault_id, program_id)
        lp_mint, _ = _derive_vault_lp_mint_pda(vault_id, program_id)
        stake, _ = _derive_vault_stake_pda(user, vault_id, program_id)
        position, _ = _derive_vault_position_lp_pda(user, vault_id, program_id)
        cal_escrow, _ = _derive_vault_cal_escrow_pda(vault_id, program_id)
        addresses = {
            "rehearsal_program": program_id,
            "rehearsal_program_config": config,
            "rehearsal_vault_counter": counter,
            "rehearsal_dung_mint_state": dung_state,
            "rehearsal_cal_mint": cal_mint,
            "rehearsal_dung_mint": dung_mint,
            "rehearsal_usdc_mint": usdc_mint,
            "rehearsal_usdc_treasury": usdc_treasury,
            "rehearsal_user_cal_ata": _derive_ata(user, cal_mint),
            "rehearsal_user_dung_ata": _derive_ata(user, dung_mint),
            "rehearsal_user_usdc_ata": _derive_ata(user, usdc_mint),
            "rehearsal_climb": climb_pda,
            "rehearsal_expected_vault": expected_vault,
            "rehearsal_vault_activation": activation,
            "rehearsal_record_board": board,
            "rehearsal_local_legend": legend,
            "rehearsal_vault_lp_mint": lp_mint,
            "rehearsal_vault_stake": stake,
            "rehearsal_position_lp": position,
            "rehearsal_cal_escrow": cal_escrow,
            "rehearsal_dung_pot": derive_vault_pot_address(
                vault_id, program_id, dung_mint
            ),
        }
        if program_data is not None:
            addresses["rehearsal_program_data"] = program_data
        if pol_account is not None:
            addresses["rehearsal_dung_pol"] = pol_account
        if dung_treasury is not None:
            addresses["rehearsal_dung_treasury"] = dung_treasury
        return addresses

    @classmethod
    async def _resolve_rehearsal_addresses(
        cls,
        *,
        rpc_url: str,
        program_id: Pubkey,
        cal_mint: Pubkey,
        dung_mint: Pubkey,
        usdc_mint: Pubkey,
        usdc_treasury: Pubkey,
        user: Pubkey,
        climb_pda: Pubkey,
        vault_id: int,
        expected_vault: Pubkey,
    ) -> dict[str, Pubkey]:
        config, _ = _derive_program_config_pda(program_id)
        discovery = {
            "rehearsal_program": program_id,
            "rehearsal_program_config": config,
        }
        _, snapshot = await cls._read_accounts(rpc_url, discovery)
        if not all(item["exists"] for item in snapshot.values()):
            raise RuntimeError("rehearsal program/config discovery is incomplete")
        program_data = _pubkey_value(
            (snapshot["rehearsal_program"].get("decoded") or {}).get(
                "program_data_address"
            ),
            "rehearsal ProgramData",
        )
        fields = _decoded_fields(snapshot["rehearsal_program_config"])
        configured = {
            "cal": _pubkey_value(
                _field_value(fields, "cal_mint", "calMint"),
                "rehearsal configured CAL mint",
            ),
            "dung": _pubkey_value(
                _field_value(fields, "dung_mint", "dungMint"),
                "rehearsal configured DUNG mint",
            ),
            "usdc": _pubkey_value(
                _field_value(fields, "usdc_mint", "usdcMint"),
                "rehearsal configured USDC mint",
            ),
            "usdc_treasury": _pubkey_value(
                _field_value(
                    fields,
                    "usdc_treasury_token_account",
                    "usdcTreasuryTokenAccount",
                ),
                "rehearsal configured USDC treasury",
            ),
        }
        if configured != {
            "cal": cal_mint,
            "dung": dung_mint,
            "usdc": usdc_mint,
            "usdc_treasury": usdc_treasury,
        }:
            raise RuntimeError("rehearsal evidence identities do not match ProgramConfig")
        pol = _pubkey_value(
            _field_value(fields, "pol_token_account", "polTokenAccount"),
            "rehearsal DUNG POL",
        )
        treasury = _pubkey_value(
            _field_value(fields, "treasury_token_account", "treasuryTokenAccount"),
            "rehearsal DUNG treasury",
        )
        return cls._rehearsal_addresses(
            program_id=program_id,
            cal_mint=cal_mint,
            dung_mint=dung_mint,
            usdc_mint=usdc_mint,
            usdc_treasury=usdc_treasury,
            user=user,
            climb_pda=climb_pda,
            vault_id=vault_id,
            expected_vault=expected_vault,
            program_data=program_data,
            pol_account=pol,
            dung_treasury=treasury,
        )

    @classmethod
    async def _read_accounts(
        cls,
        rpc_url: str,
        addresses: dict[str, Pubkey],
    ) -> tuple[int, dict[str, dict[str, Any]]]:
        labels = tuple(addresses)
        async with AsyncClient(rpc_url, commitment=Finalized) as client:
            response = await client.get_multiple_accounts(
                [addresses[label] for label in labels],
                commitment=Finalized,
            )
        values = tuple(response.value)
        if len(values) != len(labels):
            raise RuntimeError("rehearsal evidence account snapshot is incomplete")
        snapshot = {
            label: cls._account_evidence(label, addresses[label], account)
            for label, account in zip(labels, values)
        }
        return int(response.context.slot), snapshot

    @staticmethod
    def _account_evidence(
        label: str,
        address: Pubkey,
        account: object | None,
    ) -> dict[str, Any]:
        if account is None:
            return {
                "address": str(address),
                "exists": False,
                "owner": None,
                "lamports": None,
                "executable": None,
                "data_len": 0,
                "data_sha256": None,
                "decoded": None,
            }
        data = _account_data_bytes(getattr(account, "data"))
        decoded: dict[str, Any] | None = None
        owner = Pubkey.from_string(str(getattr(account, "owner")))
        if owner == BPF_UPGRADEABLE_LOADER_ID and label.endswith("_program"):
            if len(data) < 36 or struct.unpack_from("<I", data, 0)[0] != 2:
                decoded = {"decode_error": "UpgradeableLoaderProgram layout mismatch"}
            else:
                decoded = {
                    "loader_state": "Program",
                    "program_data_address": str(Pubkey.from_bytes(data[4:36])),
                }
        elif owner == BPF_UPGRADEABLE_LOADER_ID and label.endswith("_program_data"):
            if len(data) < 45 or struct.unpack_from("<I", data, 0)[0] != 3:
                decoded = {
                    "decode_error": "UpgradeableLoaderProgramData layout mismatch"
                }
            else:
                has_authority = data[12] == 1
                decoded = {
                    "loader_state": "ProgramData",
                    "slot": str(struct.unpack_from("<Q", data, 4)[0]),
                    "upgrade_authority": (
                        str(Pubkey.from_bytes(data[13:45]))
                        if has_authority
                        else None
                    ),
                    "program_bytes_sha256": hashlib.sha256(data[45:]).hexdigest(),
                }
        elif owner == TOKEN_PROGRAM_ID and len(data) == 82:
            mint_authority = (
                str(Pubkey.from_bytes(data[4:36]))
                if struct.unpack_from("<I", data, 0)[0] == 1
                else None
            )
            freeze_authority = (
                str(Pubkey.from_bytes(data[50:82]))
                if struct.unpack_from("<I", data, 46)[0] == 1
                else None
            )
            decoded = {
                "supply_base_units": str(struct.unpack_from("<Q", data, 36)[0]),
                "decimals": int(data[44]),
                "initialized": bool(data[45]),
                "mint_authority": mint_authority,
                "freeze_authority": freeze_authority,
            }
        elif owner == TOKEN_PROGRAM_ID and len(data) == 165:
            decoded = {
                "mint": str(Pubkey.from_bytes(data[0:32])),
                "token_owner": str(Pubkey.from_bytes(data[32:64])),
                "amount_base_units": str(struct.unpack_from("<Q", data, 64)[0]),
                "state": int(data[108]),
            }
        elif owner == ADDRESS_LOOKUP_TABLE_PROGRAM_ID:
            try:
                table = AddressLookupTable.deserialize(data)
                decoded = {
                    "lookup_table_authority": (
                        str(table.meta.authority)
                        if table.meta.authority is not None
                        else None
                    ),
                    "deactivation_slot": str(table.meta.deactivation_slot),
                    "last_extended_slot": str(table.meta.last_extended_slot),
                    "address_count": len(table.addresses),
                    "addresses": [str(value) for value in table.addresses],
                    "addresses_sha256": hashlib.sha256(
                        b"".join(bytes(value) for value in table.addresses)
                    ).hexdigest(),
                }
            except Exception as exc:
                decoded = {"decode_error": type(exc).__name__}
        elif label.endswith("vault_counter"):
            counter = parse_vault_counter(data)
            decoded = (
                {"count": str(counter.count), "bump": counter.bump}
                if counter is not None
                else {"decode_error": "VaultCounter layout mismatch"}
            )
        elif owner in (PROTECTED_PROGRAM_ID,) or label.startswith("rehearsal_"):
            try:
                parsed = _get_boulder_accounts_coder().parse(data)
                decoded = {
                    "account_type": parsed.name,
                    "fields": _json_value(vars(parsed.data)),
                }
            except Exception as exc:
                decoded = {"decode_error": type(exc).__name__}
        return {
            "address": str(address),
            "exists": True,
            "owner": str(owner),
            "lamports": int(getattr(account, "lamports")),
            "executable": bool(getattr(account, "executable", False)),
            "data_len": len(data),
            "data_sha256": hashlib.sha256(data).hexdigest(),
            "decoded": decoded,
        }

    @staticmethod
    def _require_baseline_accounts(
        protected: dict[str, dict[str, Any]],
        rehearsal: dict[str, dict[str, Any]],
        *,
        fresh: bool,
    ) -> None:
        protected_required = {
            "protected_program",
            "protected_program_data",
            "protected_program_config",
            "protected_vault_counter",
            "protected_dung_mint_state",
            "protected_cal_mint",
            "protected_dung_mint",
            "protected_test_usdc_mint",
            "protected_usdc_treasury",
            "protected_dung_pol",
            "protected_dung_treasury",
            "protected_shawmont_climb",
        }
        rehearsal_required = {
            "rehearsal_program",
            "rehearsal_program_data",
            "rehearsal_program_config",
            "rehearsal_vault_counter",
            "rehearsal_dung_mint_state",
            "rehearsal_cal_mint",
            "rehearsal_dung_mint",
            "rehearsal_usdc_mint",
            "rehearsal_usdc_treasury",
            "rehearsal_dung_pol",
            "rehearsal_dung_treasury",
            "rehearsal_user_cal_ata",
            "rehearsal_user_usdc_ata",
            "rehearsal_climb",
        }
        if not fresh:
            rehearsal_required.update(
                {
                    "rehearsal_expected_vault",
                    "rehearsal_vault_activation",
                    "rehearsal_record_board",
                    "rehearsal_local_legend",
                }
            )
        missing = [
            label
            for label in sorted(protected_required | rehearsal_required)
            if not ({**protected, **rehearsal}.get(label) or {}).get("exists")
        ]
        if missing:
            raise RuntimeError(
                "rehearsal evidence baseline is missing: " + ", ".join(missing)
            )
        expected_vault_exists = rehearsal["rehearsal_expected_vault"]["exists"]
        if fresh and expected_vault_exists:
            raise RuntimeError(
                "expected fresh rehearsal Vault already exists; use exact resume mode"
            )
        if not fresh and not expected_vault_exists:
            raise RuntimeError("resume Vault is absent from finalized rehearsal state")

        rehearsal_program = rehearsal["rehearsal_program"]["address"]
        wrong_owners = [
            label
            for label, item in rehearsal.items()
            if item.get("exists")
            and (
                (label in {"rehearsal_program", "rehearsal_program_data"}
                 and item.get("owner") != str(BPF_UPGRADEABLE_LOADER_ID))
                or (
                    label.startswith("rehearsal_")
                    and label
                    not in {
                        "rehearsal_program",
                        "rehearsal_program_data",
                        "rehearsal_cal_mint",
                        "rehearsal_dung_mint",
                        "rehearsal_usdc_mint",
                        "rehearsal_usdc_treasury",
                        "rehearsal_dung_pol",
                        "rehearsal_dung_treasury",
                        "rehearsal_user_cal_ata",
                        "rehearsal_user_dung_ata",
                        "rehearsal_user_usdc_ata",
                        "rehearsal_vault_lp_mint",
                        "rehearsal_position_lp",
                        "rehearsal_cal_escrow",
                        "rehearsal_dung_pot",
                    }
                    and item.get("owner") != rehearsal_program
                )
            )
        ]
        if wrong_owners:
            raise RuntimeError(
                "rehearsal evidence account ownership mismatch: "
                + ", ".join(sorted(wrong_owners))
            )

    @staticmethod
    def _validate_rehearsal_authorities(
        snapshot: dict[str, dict[str, Any]],
        identity: dict[str, Any],
    ) -> None:
        program_id = str(identity["program_id"])
        user = str(identity["user"])
        vault = str(identity["expected_vault"])
        cal_mint = str(identity["cal_mint"])
        dung_mint = str(identity["dung_mint"])
        usdc_mint = str(identity["usdc_mint"])
        config_fields = _decoded_fields(snapshot.get("rehearsal_program_config") or {})
        admin = str(_field_value(config_fields, "admin_authority", "adminAuthority"))
        program = snapshot.get("rehearsal_program") or {}
        program_data = snapshot.get("rehearsal_program_data") or {}
        if (
            not program.get("exists")
            or not program.get("executable")
            or program.get("owner") != str(BPF_UPGRADEABLE_LOADER_ID)
            or (program.get("decoded") or {}).get("loader_state") != "Program"
            or (program.get("decoded") or {}).get("program_data_address")
            != program_data.get("address")
            or not program_data.get("exists")
            or program_data.get("owner") != str(BPF_UPGRADEABLE_LOADER_ID)
            or (program_data.get("decoded") or {}).get("loader_state")
            != "ProgramData"
        ):
            raise RuntimeError("rehearsal Program/ProgramData link is invalid")
        if (
            (snapshot.get("rehearsal_program_config", {}).get("decoded") or {}).get(
                "account_type"
            )
            != "ProgramConfig"
            or admin in {"None", str(Pubkey.default())}
        ):
            raise RuntimeError("rehearsal ProgramConfig identity is invalid")
        configured_addresses = {
            "cal_mint": cal_mint,
            "dung_mint": dung_mint,
            "usdc_mint": usdc_mint,
            "usdc_treasury_token_account": str(identity["usdc_treasury"]),
            "pol_token_account": (
                snapshot.get("rehearsal_dung_pol") or {}
            ).get("address"),
            "treasury_token_account": (
                snapshot.get("rehearsal_dung_treasury") or {}
            ).get("address"),
        }
        for field, expected in configured_addresses.items():
            camel = field.split("_")[0] + "".join(
                part.capitalize() for part in field.split("_")[1:]
            )
            if _field_value(config_fields, field, camel) != expected:
                raise RuntimeError(
                    f"rehearsal ProgramConfig {field} changed after evidence binding"
                )
        if "count" not in (
            snapshot.get("rehearsal_vault_counter", {}).get("decoded") or {}
        ):
            raise RuntimeError("rehearsal VaultCounter failed exact decoding")
        if (
            snapshot.get("rehearsal_dung_mint_state", {}).get("decoded") or {}
        ).get("account_type") != "DungMintState":
            raise RuntimeError("rehearsal DungMintState failed exact decoding")

        def require_token(
            label: str,
            *,
            mint: str,
            token_owner: str | None = None,
            optional: bool = False,
        ) -> None:
            item = snapshot.get(label) or {}
            if not item.get("exists"):
                if optional:
                    return
                raise RuntimeError(f"rehearsal evidence is missing {label}")
            decoded = item.get("decoded") or {}
            if item.get("owner") != str(TOKEN_PROGRAM_ID) or decoded.get("mint") != mint:
                raise RuntimeError(f"{label} has the wrong SPL mint/owner")
            if token_owner is not None and decoded.get("token_owner") != token_owner:
                raise RuntimeError(f"{label} has the wrong token authority")

        for label, mint in (
            ("rehearsal_cal_mint", cal_mint),
            ("rehearsal_dung_mint", dung_mint),
            ("rehearsal_usdc_mint", usdc_mint),
        ):
            item = snapshot.get(label) or {}
            if (
                not item.get("exists")
                or item.get("address") != mint
                or item.get("owner") != str(TOKEN_PROGRAM_ID)
                or "supply_base_units" not in (item.get("decoded") or {})
            ):
                raise RuntimeError(f"{label} is not the exact classic SPL mint")
        require_token("rehearsal_user_cal_ata", mint=cal_mint, token_owner=user)
        require_token(
            "rehearsal_user_dung_ata",
            mint=dung_mint,
            token_owner=user,
            optional=True,
        )
        require_token("rehearsal_user_usdc_ata", mint=usdc_mint, token_owner=user)
        require_token(
            "rehearsal_usdc_treasury", mint=usdc_mint, token_owner=admin
        )
        require_token("rehearsal_dung_pol", mint=dung_mint)
        require_token("rehearsal_dung_treasury", mint=dung_mint)
        usdc_decoded = (
            snapshot.get("rehearsal_usdc_mint", {}).get("decoded") or {}
        )
        if (
            usdc_decoded.get("decimals") != 6
            or usdc_decoded.get("mint_authority") is not None
            or usdc_decoded.get("freeze_authority") is not None
        ):
            raise RuntimeError("rehearsal USDC mint authority/decimals/freeze state changed")
        expected_supply = int(identity.get("initial_usdc_supply") or 0)
        if expected_supply > 0:
            actual_supply = int(usdc_decoded.get("supply_base_units", -1))
            rider_balance = int(
                (
                    snapshot.get("rehearsal_user_usdc_ata", {}).get("decoded")
                    or {}
                ).get("amount_base_units", -1)
            )
            treasury_balance = int(
                (
                    snapshot.get("rehearsal_usdc_treasury", {}).get("decoded")
                    or {}
                ).get("amount_base_units", -1)
            )
            if (
                actual_supply != expected_supply
                or rider_balance + treasury_balance != expected_supply
            ):
                raise RuntimeError("rehearsal USDC supply/balances no longer reconcile")

        expected_anchor_types = {
            "rehearsal_climb": "Climb",
            "rehearsal_expected_vault": "Vault",
            "rehearsal_vault_activation": "VaultActivation",
            "rehearsal_record_board": "VaultLeaderboard",
            "rehearsal_local_legend": "LocalLegend",
            "rehearsal_vault_stake": "VaultStake",
            "rehearsal_rider_soul": "RiderSoul",
            "rehearsal_completion_ride_attestation": "RideAttestation",
            "rehearsal_completion_tribute_budget": "RideTributeBudget",
            "rehearsal_completion_cal_receipt": "CalMintReceipt",
            "rehearsal_completion_receipt": "ClimbCompletionReceiptV2",
            "rehearsal_vault_completion": "VaultCompletion",
        }
        for label, account_type in expected_anchor_types.items():
            item = snapshot.get(label) or {}
            if item.get("exists") and (
                item.get("owner") != program_id
                or (item.get("decoded") or {}).get("account_type") != account_type
            ):
                raise RuntimeError(f"{label} account type/owner changed")
        for label, item in snapshot.items():
            if not item.get("exists"):
                continue
            account_type = None
            if label.endswith("_ride_attestation"):
                account_type = "RideAttestation"
            elif label.endswith("_cal_receipt"):
                account_type = "CalMintReceipt"
            if account_type is not None and (
                item.get("owner") != program_id
                or (item.get("decoded") or {}).get("account_type") != account_type
            ):
                raise RuntimeError(f"{label} account type/owner changed")
        require_token(
            "rehearsal_cal_escrow",
            mint=cal_mint,
            token_owner=vault,
            optional=True,
        )
        require_token(
            "rehearsal_dung_pot",
            mint=dung_mint,
            token_owner=vault,
            optional=True,
        )
        stake = (snapshot.get("rehearsal_vault_stake") or {}).get("address")
        lp_mint = (snapshot.get("rehearsal_vault_lp_mint") or {}).get("address")
        if stake and lp_mint:
            require_token(
                "rehearsal_position_lp",
                mint=str(lp_mint),
                token_owner=str(stake),
                optional=True,
            )
            lp = snapshot.get("rehearsal_vault_lp_mint") or {}
            if lp.get("exists"):
                decoded = lp.get("decoded") or {}
                if (
                    lp.get("owner") != str(TOKEN_PROGRAM_ID)
                    or decoded.get("mint_authority") != vault
                    or decoded.get("freeze_authority") != vault
                ):
                    raise RuntimeError(
                        "rehearsal Vault LP mint does not use Vault mint/freeze authority"
                    )

        for label, item in snapshot.items():
            if not item.get("exists"):
                continue
            if label.startswith("rehearsal_settlement_lookup_table") or label.startswith(
                "rehearsal_settlement_recipient_dung_ata_"
            ):
                continue
            if label.startswith("rehearsal_") and label not in {
                "rehearsal_program",
                "rehearsal_program_data",
                "rehearsal_cal_mint",
                "rehearsal_dung_mint",
                "rehearsal_usdc_mint",
                "rehearsal_usdc_treasury",
                "rehearsal_dung_pol",
                "rehearsal_dung_treasury",
                "rehearsal_user_cal_ata",
                "rehearsal_user_dung_ata",
                "rehearsal_user_usdc_ata",
                "rehearsal_vault_lp_mint",
                "rehearsal_position_lp",
                "rehearsal_cal_escrow",
                "rehearsal_dung_pot",
            } and item.get("owner") != program_id:
                raise RuntimeError(f"{label} is not owned by the rehearsal program")

    @staticmethod
    def _fingerprint(evidence: dict[str, Any]) -> dict[str, Any]:
        return {
            key: evidence.get(key)
            for key in ("address", "exists", "owner", "data_len", "data_sha256", "decoded")
        }

    @classmethod
    def _assert_protected_baseline(
        cls,
        expected: dict[str, dict[str, Any]],
        actual: dict[str, dict[str, Any]],
    ) -> None:
        if set(expected) != set(actual):
            raise RuntimeError("protected account baseline labels changed")
        mismatched = [
            label
            for label in expected
            if cls._fingerprint(expected[label]) != cls._fingerprint(actual[label])
        ]
        if mismatched:
            raise RuntimeError(
                "protected account baseline changed: " + ", ".join(mismatched)
            )

    @property
    def vault_id(self) -> int:
        return int(self._state["identity"]["vault_id"])

    @property
    def climb_pda(self) -> Pubkey:
        return Pubkey.from_string(self._state["identity"]["climb_pda"])

    @property
    def expected_vault(self) -> Pubkey:
        return Pubkey.from_string(self._state["identity"]["expected_vault"])

    def has_reconciliation(self, stage: str) -> bool:
        return any(
            item.get("stage") == stage
            for item in self._state.get("reconciliations", ())
        )

    def has_finalized_instruction(self, instruction_name: str) -> bool:
        return self.finalized_signature_for_instruction(instruction_name) is not None

    def finalized_signature_for_instruction(
        self, instruction_name: str
    ) -> str | None:
        matches = [
            str(item["signature"])
            for item in self._state.get("transactions", ())
            if item.get("status") == "finalized"
            and any(
                instruction.get("instruction_name") == instruction_name
                for instruction in item.get("instruction_order", ())
            )
        ]
        if len(matches) > 1:
            raise RuntimeError(
                f"multiple finalized {instruction_name} transactions in rehearsal evidence"
            )
        return matches[0] if matches else None

    @property
    def protected_accounts(self) -> set[str]:
        return set(self._state["protected_addresses"].values())

    def _current_rehearsal_addresses(self) -> dict[str, Pubkey]:
        combined = {
            **self._state.get("rehearsal_addresses", {}),
            **self._state.get("dynamic_rehearsal_addresses", {}),
        }
        return {
            label: Pubkey.from_string(address)
            for label, address in combined.items()
        }

    async def read_rehearsal_accounts(self) -> dict[str, dict[str, Any]]:
        _, snapshot = await self._read_accounts(
            self.rpc_url,
            self._current_rehearsal_addresses(),
        )
        return snapshot

    def register_completion_evidence(
        self,
        *,
        ride_hash: bytes,
    ) -> None:
        identity = self._state["identity"]
        program_id = Pubkey.from_string(identity["program_id"])
        rider = Pubkey.from_string(identity["user"])
        vault = Pubkey.from_string(identity["expected_vault"])
        attestation, _ = _derive_ride_attestation_pda(
            rider, ride_hash, program_id
        )
        budget, _ = _derive_ride_tribute_budget_pda(attestation, program_id)
        cal_receipt, _ = _derive_cal_mint_receipt_pda(
            attestation, rider, program_id
        )
        completion_receipt, _ = _derive_climb_completion_receipt_pda(
            attestation, vault, program_id
        )
        completion, _ = _derive_vault_completion_pda(
            rider, self.vault_id, program_id
        )
        additions = {
            "rehearsal_rider_soul": str(
                _derive_rider_soul_pda(rider, program_id)[0]
            ),
            "rehearsal_completion_ride_attestation": str(attestation),
            "rehearsal_completion_tribute_budget": str(budget),
            "rehearsal_completion_cal_receipt": str(cal_receipt),
            "rehearsal_completion_receipt": str(completion_receipt),
            "rehearsal_vault_completion": str(completion),
        }
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                dynamic = self._state.setdefault("dynamic_rehearsal_addresses", {})
                for label, address in additions.items():
                    existing = dynamic.get(label)
                    if existing is not None and existing != address:
                        raise RuntimeError(
                            f"rehearsal deterministic account {label} changed on resume"
                        )
                    dynamic[label] = address
                _atomic_write(self.path, self._state)

    def register_cal_credit_evidence(
        self,
        *,
        label: str,
        activity_id: str,
    ) -> None:
        if not label or not label.replace("_", "").isalnum():
            raise RuntimeError("deterministic CAL evidence label is invalid")
        identity = self._state["identity"]
        program_id = Pubkey.from_string(identity["program_id"])
        rider = Pubkey.from_string(identity["user"])
        ride_hash = hashlib.sha256(activity_id.encode("utf-8")).digest()
        attestation, _ = _derive_ride_attestation_pda(
            rider, ride_hash, program_id
        )
        receipt, _ = _derive_cal_mint_receipt_pda(
            attestation, rider, program_id
        )
        additions = {
            "rehearsal_rider_soul": str(
                _derive_rider_soul_pda(rider, program_id)[0]
            ),
            f"rehearsal_{label}_ride_attestation": str(attestation),
            f"rehearsal_{label}_cal_receipt": str(receipt),
        }
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                dynamic = self._state.setdefault("dynamic_rehearsal_addresses", {})
                for item_label, address in additions.items():
                    existing = dynamic.get(item_label)
                    if existing is not None and existing != address:
                        raise RuntimeError(
                            f"rehearsal deterministic account {item_label} changed"
                        )
                    dynamic[item_label] = address
                _atomic_write(self.path, self._state)

    async def register_settlement_transport_plan(
        self,
        plan: dict[str, Any],
    ) -> None:
        """Freeze ALT/recipient identities before their first transport mutation."""
        self._reload_current_state()
        try:
            lookup_table = Pubkey.from_string(str(plan["lookup_table_address"]))
            authority = Pubkey.from_string(str(plan["lookup_table_authority"]))
            generation = int(plan["lookup_table_generation"])
            recipients = [dict(value) for value in plan["recipient_token_accounts"]]
            plan_sha256 = str(plan["plan_sha256"])
            recent_slot = int(plan["lookup_table_recent_slot"])
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("settlement transport plan identity is malformed") from exc
        unhashed = {key: value for key, value in plan.items() if key != "plan_sha256"}
        expected_hash = hashlib.sha256(
            json.dumps(unhashed, sort_keys=True, separators=(",", ":")).encode(
                "ascii"
            )
        ).hexdigest()
        if generation <= 0 or plan_sha256 != expected_hash:
            raise RuntimeError("settlement transport plan generation/hash is invalid")
        identity = self._state["identity"]
        if (
            str(plan.get("program_id")) != str(identity["program_id"])
            or str(plan.get("vault_id")) != str(identity["vault_id"])
            or str(plan.get("settlement_week"))
            != str(identity.get("settlement_week"))
            or str(plan.get("payer")) != str(authority)
            or derive_lookup_table_address(authority, recent_slot)[0] != lookup_table
        ):
            raise RuntimeError("settlement transport plan identity is not evidence-bound")
        instruction = plan.get("distribution_instruction") or {}
        instruction_accounts = instruction.get("accounts") or []
        recomputed_required = list(
            dict.fromkeys(
                str(meta.get("pubkey"))
                for meta in instruction_accounts
                if not bool(meta.get("is_signer"))
            )
        )
        if recomputed_required != list(plan.get("required_addresses") or ()):
            raise RuntimeError("settlement required-address manifest changed")
        if str(instruction.get("program_id")) != str(identity["program_id"]):
            raise RuntimeError("settlement instruction program is not rehearsal-bound")
        additions = {"rehearsal_settlement_lookup_table": str(lookup_table)}
        normalized_recipients: list[dict[str, str]] = []
        seen_recipient_atas: set[str] = set()
        dung_mint = str(identity["dung_mint"])
        for index, recipient in enumerate(recipients):
            try:
                ata = Pubkey.from_string(str(recipient["ata"]))
                owner = Pubkey.from_string(str(recipient["owner"]))
                mint = Pubkey.from_string(str(recipient["mint"]))
            except (KeyError, ValueError) as exc:
                raise RuntimeError("settlement recipient manifest is malformed") from exc
            normalized_recipients.append(
                {"ata": str(ata), "owner": str(owner), "mint": str(mint)}
            )
            if (
                str(mint) != dung_mint
                or ata != _derive_ata(owner, mint)
                or str(ata) in seen_recipient_atas
            ):
                raise RuntimeError("settlement recipient manifest is not canonical")
            seen_recipient_atas.add(str(ata))
            additions[f"rehearsal_settlement_recipient_dung_ata_{index}"] = str(
                ata
            )
        frozen_plan = _json_value(plan)
        supersedes = frozen_plan.pop("supersedes", None)
        normalized_unhashed = {
            key: value for key, value in frozen_plan.items() if key != "plan_sha256"
        }
        frozen_plan["plan_sha256"] = hashlib.sha256(
            json.dumps(
                normalized_unhashed, sort_keys=True, separators=(",", ":")
            ).encode("ascii")
        ).hexdigest()
        existing_plan = self._state.get("settlement_transport_plan")
        expired_label: str | None = None
        if existing_plan is None and supersedes is not None:
            raise RuntimeError("settlement transport supersession has no prior plan")
        if existing_plan is not None and existing_plan != frozen_plan:
            if not isinstance(supersedes, dict):
                raise RuntimeError("settlement transport plan changed on resume")
            if any(
                item.get("status") == "expired"
                for item in self._state.get("settlement_transport_plan_history", ())
            ):
                raise RuntimeError(
                    "settlement transport plan already used its one supersession"
                )
            expected_supersession = {
                "status": "expired",
                "generation_id": existing_plan.get(
                    "lookup_table_generation_id"
                ),
                "lookup_table_address": existing_plan.get(
                    "lookup_table_address"
                ),
                "lookup_table_generation": existing_plan.get(
                    "lookup_table_generation"
                ),
                "lookup_table_recent_slot": existing_plan.get(
                    "lookup_table_recent_slot"
                ),
                "proof": "finalized create rejection after recent slot",
            }
            if supersedes != expected_supersession or generation != int(
                existing_plan["lookup_table_generation"]
            ) + 1:
                raise RuntimeError("settlement transport supersession is invalid")
            mutable = {
                "lookup_table_generation_id",
                "lookup_table_address",
                "lookup_table_generation",
                "lookup_table_recent_slot",
                "expected_manifest_sha256",
                "plan_sha256",
                "supersedes",
            }
            old_intent = {
                key: value for key, value in existing_plan.items() if key not in mutable
            }
            new_intent = {
                key: value for key, value in frozen_plan.items() if key not in mutable
            }
            if old_intent != new_intent:
                raise RuntimeError(
                    "settlement transport intent changed during supersession"
                )
            expired_label = (
                "rehearsal_settlement_lookup_table_expired_"
                + str(existing_plan["lookup_table_generation"])
            )
            additions[expired_label] = str(existing_plan["lookup_table_address"])
        protected = self.protected_accounts
        overlap = sorted(set(additions.values()).intersection(protected))
        if overlap:
            raise RuntimeError(
                "settlement transport plan overlaps protected canonical accounts: "
                + ", ".join(overlap)
            )
        # Snapshot before persistence so existing foreign token/ALT accounts fail closed.
        _, snapshot = await self._read_accounts(
            self.rpc_url,
            {label: Pubkey.from_string(address) for label, address in additions.items()},
        )
        lookup = snapshot["rehearsal_settlement_lookup_table"]
        if lookup.get("exists") and lookup.get("owner") != str(
            ADDRESS_LOOKUP_TABLE_PROGRAM_ID
        ):
            raise RuntimeError("planned settlement lookup table has a foreign owner")
        if lookup.get("exists"):
            decoded_lookup = lookup.get("decoded") or {}
            current_addresses = list(decoded_lookup.get("addresses") or ())
            required_addresses = list(frozen_plan.get("required_addresses") or ())
            if (
                decoded_lookup.get("decode_error")
                or decoded_lookup.get("lookup_table_authority") != str(authority)
                or current_addresses
                != required_addresses[: len(current_addresses)]
            ):
                raise RuntimeError(
                    "planned settlement lookup table is not an exact frozen prefix"
                )
        if expired_label is not None and snapshot[expired_label].get("exists"):
            raise RuntimeError(
                "expired settlement lookup table unexpectedly exists; rotation refused"
            )
        for label, item in snapshot.items():
            if label.startswith("rehearsal_settlement_lookup_table") or not item.get(
                "exists"
            ):
                continue
            decoded = item.get("decoded") or {}
            recipient = normalized_recipients[
                int(label.rsplit("_", 1)[-1])
            ]
            if (
                recipient["mint"] != dung_mint
                or item.get("owner") != str(TOKEN_PROGRAM_ID)
                or decoded.get("mint") != dung_mint
                or decoded.get("token_owner") != recipient["owner"]
                or decoded.get("state") not in (1, 2)
            ):
                raise RuntimeError(f"{label} has a foreign token identity")
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                existing_plan = self._state.get("settlement_transport_plan")
                history = self._state.setdefault("settlement_transport_plan_history", [])
                if not history and existing_plan is not None:
                    history.append({"status": "planned", "plan": existing_plan})
                if existing_plan is not None and existing_plan != frozen_plan:
                    if not history or history[-1].get("plan") != existing_plan:
                        raise RuntimeError("settlement transport history changed")
                    history[-1] = {
                        "status": "expired",
                        "plan": existing_plan,
                        "proof": supersedes,
                    }
                    history.append({"status": "planned", "plan": frozen_plan})
                elif existing_plan is None:
                    history.append({"status": "planned", "plan": frozen_plan})
                dynamic = self._state.setdefault("dynamic_rehearsal_addresses", {})
                if expired_label is not None:
                    prior_address = dynamic.get("rehearsal_settlement_lookup_table")
                    if prior_address != additions[expired_label]:
                        raise RuntimeError("settlement transport prior address changed")
                    dynamic[expired_label] = prior_address
                for label, address in additions.items():
                    existing = dynamic.get(label)
                    if (
                        existing is not None
                        and existing != address
                        and not (
                            label == "rehearsal_settlement_lookup_table"
                            and expired_label is not None
                        )
                    ):
                        raise RuntimeError(
                            f"settlement transport address {label} changed on resume"
                        )
                    dynamic[label] = address
                self._state["settlement_transport_plan"] = frozen_plan
                _atomic_write(self.path, self._state)

    def validate_settlement_transport_snapshot(
        self,
        snapshot: dict[str, dict[str, Any]],
    ) -> dict[str, Any]:
        plan = self._state.get("settlement_transport_plan")
        if not isinstance(plan, dict):
            raise RuntimeError("settlement transport plan was not frozen")
        ready = self._state.get("settlement_transport_ready")
        if (
            not isinstance(ready, dict)
            or ready.get("lookup_table_address") != plan.get("lookup_table_address")
            or ready.get("lookup_table_generation")
            != plan.get("lookup_table_generation")
        ):
            raise RuntimeError("settlement transport ready manifest was not frozen")
        lookup = snapshot.get("rehearsal_settlement_lookup_table") or {}
        decoded = lookup.get("decoded") or {}
        if (
            not lookup.get("exists")
            or lookup.get("address") != plan.get("lookup_table_address")
            or lookup.get("owner") != str(ADDRESS_LOOKUP_TABLE_PROGRAM_ID)
            or decoded.get("decode_error")
            or decoded.get("lookup_table_authority")
            != plan.get("lookup_table_authority")
            or int(decoded.get("deactivation_slot", -1))
            != 18_446_744_073_709_551_615
            or str(decoded.get("last_extended_slot"))
            != str(ready.get("last_extended_slot"))
            or str(decoded.get("address_count"))
            != str(ready.get("lookup_table_address_count"))
            or list(decoded.get("addresses") or ())
            != list(plan.get("required_addresses") or ())
        ):
            raise RuntimeError("settlement lookup table evidence is not active/owned")
        dung_mint = str(self._state["identity"]["dung_mint"])
        missing: list[str] = []
        recipients = list(plan.get("recipient_token_accounts", ()))
        for index, recipient in enumerate(recipients):
            address = str(recipient.get("ata"))
            label = f"rehearsal_settlement_recipient_dung_ata_{index}"
            item = snapshot.get(label) or {}
            token = item.get("decoded") or {}
            if (
                not item.get("exists")
                or item.get("address") != address
                or item.get("owner") != str(TOKEN_PROGRAM_ID)
                or token.get("mint") != dung_mint
                or token.get("token_owner") != str(recipient.get("owner"))
                or token.get("state") not in (1, 2)
            ):
                missing.append(label)
        if missing:
            raise RuntimeError(
                "settlement recipient account evidence is missing/foreign: "
                + ", ".join(missing)
            )
        return {
            "plan": plan,
            "ready": ready,
            "lookup_table": self._fingerprint(lookup),
            "recipient_count": len(recipients),
        }

    def confirm_settlement_transport_ready(self, result: dict[str, Any]) -> None:
        """Bind the manager's final manifest to the pre-submit transport plan."""
        self._reload_current_state()
        plan = self._state.get("settlement_transport_plan")
        if not isinstance(plan, dict):
            raise RuntimeError("settlement transport result has no frozen plan")
        try:
            frozen_result = {
                "lookup_table_address": str(result["lookup_table_address"]),
                "lookup_table_generation": str(result["lookup_table_generation"]),
                "manifest_sha256": str(result["manifest_sha256"]),
                "last_extended_slot": str(result["last_extended_slot"]),
                "lookup_table_address_count": str(
                    result["lookup_table_address_count"]
                ),
                "required_account_count": str(result["required_account_count"]),
            }
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError("settlement transport ready result is incomplete") from exc
        if (
            frozen_result["lookup_table_address"]
            != plan["lookup_table_address"]
            or frozen_result["lookup_table_generation"]
            != plan["lookup_table_generation"]
            or len(frozen_result["manifest_sha256"]) != 64
            or frozen_result["manifest_sha256"]
            != plan.get("expected_manifest_sha256")
            or int(frozen_result["required_account_count"])
            != len(plan.get("required_addresses") or ())
        ):
            raise RuntimeError("settlement transport ready result changed its frozen plan")
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                existing = self._state.get("settlement_transport_ready")
                if existing is not None and existing != frozen_result:
                    raise RuntimeError("settlement transport ready result changed on resume")
                self._state["settlement_transport_ready"] = frozen_result
                _atomic_write(self.path, self._state)

    def claim_run_lock(self) -> None:
        """Hold an exclusive artifact lease for the complete rehearsal process."""
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
        with _exclusive_manifest_lock(self.path):
            yield

    def set_settlement_week(self, settlement_week: int) -> None:
        if settlement_week < 0:
            raise RuntimeError("rehearsal Settlement Week must be non-negative")
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                existing = self._state["identity"].get("settlement_week")
                if existing is not None and int(existing) != settlement_week:
                    raise RuntimeError(
                        "rehearsal Settlement Week changed after evidence was frozen"
                    )
                self._state["identity"]["settlement_week"] = settlement_week
                _atomic_write(self.path, self._state)

    def _reload_current_state(self) -> None:
        if not self.path.exists():
            return
        expected_identity = self._state.get("identity") or {}
        try:
            current = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception as exc:
            raise RuntimeError("rehearsal evidence artifact is unreadable") from exc
        expected_schema = self._state.get("schema")
        if not isinstance(current, dict) or current.get("schema") != expected_schema:
            raise RuntimeError("rehearsal evidence schema does not match")
        current_identity = current.get("identity") or {}
        immutable_fields = (
            "program_id",
            "cal_mint",
            "dung_mint",
            "usdc_mint",
            "usdc_treasury",
            "user",
            "climb_pda",
            "vault_id",
            "expected_vault",
            "transport_state_path",
            "vault_creation_cal",
            "vault_creation_cal_base_units",
            "vault_creation_usdc",
            "harvest_fee_bps",
            "user_cal",
            "stake_cal",
            "vault_alloc_cal",
            "setup_evidence_path",
            "setup_evidence_sha256",
            "initial_usdc_supply",
        )
        if any(
            current_identity.get(field) != expected_identity.get(field)
            for field in immutable_fields
        ):
            raise RuntimeError("rehearsal evidence identity changed during this run")
        self._state = current

    @staticmethod
    def _transaction_accounts(
        transaction: object,
        lookup_tables: Sequence[AddressLookupTableAccount],
    ) -> tuple[list[Pubkey], list[dict[str, Any]]]:
        message = getattr(transaction, "message")
        static_keys = list(message.account_keys)
        combined = list(static_keys)
        lookups = list(getattr(message, "address_table_lookups", ()) or ())
        if lookups:
            tables = {str(table.key): table for table in lookup_tables}
            writable: list[Pubkey] = []
            readonly: list[Pubkey] = []
            for lookup in lookups:
                table = tables.get(str(lookup.account_key))
                if table is None:
                    raise RuntimeError(
                        f"transaction lookup table {lookup.account_key} is unresolved"
                    )
                writable.extend(table.addresses[index] for index in lookup.writable_indexes)
                readonly.extend(table.addresses[index] for index in lookup.readonly_indexes)
            combined.extend(writable)
            combined.extend(readonly)

        instructions: list[dict[str, Any]] = []
        for index, instruction in enumerate(message.instructions):
            program_index = int(instruction.program_id_index)
            if program_index >= len(combined):
                raise RuntimeError("compiled transaction program index is out of bounds")
            data = bytes(instruction.data)
            discriminator = data[:8].hex() if len(data) >= 8 else data.hex()
            instructions.append(
                {
                    "index": index,
                    "program_id": str(combined[program_index]),
                    "account_indices": [int(value) for value in instruction.accounts],
                    "data_len": len(data),
                    "data_hex": data.hex(),
                    "data_sha256": hashlib.sha256(data).hexdigest(),
                    "discriminator_hex": discriminator,
                    "instruction_name": INSTRUCTION_NAMES.get(discriminator),
                }
            )
        return combined, instructions

    @staticmethod
    def _stage(metadata: dict[str, Any], instructions: list[dict[str, Any]]) -> str:
        named = [
            str(instruction["instruction_name"])
            for instruction in instructions
            if instruction.get("instruction_name")
        ]
        if named:
            return "+".join(named)
        return str(metadata.get("tx_type") or "unknown_transaction")

    @staticmethod
    def _prepared_fingerprint(entry: dict[str, Any]) -> str:
        frozen = {
            key: entry.get(key)
            for key in (
                "signature",
                "stage",
                "metadata",
                "account_set",
                "instruction_order",
            )
        }
        return hashlib.sha256(
            json.dumps(frozen, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def record_prepared_transaction(
        self,
        transaction: object,
        lookup_tables: Sequence[AddressLookupTableAccount],
        metadata: dict[str, Any],
    ) -> None:
        accounts, instructions = self._transaction_accounts(transaction, lookup_tables)
        if any(item.get("instruction_name") in {
            "admin_override_open_settlement_week", "admin_seed_pending_rewards",
            "admin_override_stake_eligibility",
        } for item in instructions):
            raise RuntimeError("TestOnlyInstructionDisabled: historical helpers cannot enter a new rehearsal")
        account_strings = [str(account) for account in accounts]
        protected = sorted(self.protected_accounts.intersection(account_strings))
        if protected:
            raise RuntimeError(
                "rehearsal transaction references protected canonical accounts: "
                + ", ".join(protected)
            )
        signature = str(getattr(transaction, "signatures")[0])
        entry = {
            "signature": signature,
            "stage": self._stage(metadata, instructions),
            "status": "prepared",
            "slot": None,
            "metadata": _json_value(metadata),
            "account_set": account_strings,
            "instruction_order": instructions,
        }
        entry["prepared_fingerprint"] = self._prepared_fingerprint(entry)
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                existing = next(
                    (
                        item
                        for item in self._state["transactions"]
                        if item["signature"] == signature
                    ),
                    None,
                )
                if existing is not None:
                    if (
                        existing["account_set"] != entry["account_set"]
                        or existing["instruction_order"] != entry["instruction_order"]
                        or existing.get("prepared_fingerprint")
                        != entry["prepared_fingerprint"]
                    ):
                        raise RuntimeError("prepared signature evidence changed on resume")
                    if existing.get("status") in {"expired", "failed"}:
                        raise RuntimeError(
                            "terminal rehearsal attempt cannot be resubmitted; rebuild "
                            "and explicitly resume with a fresh signature"
                        )
                    return
                self._state["transactions"].append(entry)
                _atomic_write(self.path, self._state)

    def record_finalized_transaction(
        self,
        signature: str,
        slot: int | None,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                entry = next(
                    (
                        item
                        for item in self._state["transactions"]
                        if item["signature"] == signature
                    ),
                    None,
                )
                if entry is None:
                    raise RuntimeError(
                        f"finalized signature {signature} has no protected-account preflight"
                    )
                prepared_fingerprint = entry.get("prepared_fingerprint")
                actual_fingerprint = self._prepared_fingerprint(entry)
                if prepared_fingerprint is None:
                    raise RuntimeError(
                        f"prepared signature {signature} has no frozen evidence fingerprint"
                    )
                if prepared_fingerprint != actual_fingerprint:
                    raise RuntimeError("prepared signature evidence changed on resume")
                status_rank = {"prepared": 0, "confirmed": 1, "finalized": 2}
                current_status = str(entry.get("status") or "")
                if status not in status_rank or current_status not in status_rank:
                    raise RuntimeError("rehearsal transaction status is invalid")
                if status_rank[status] < status_rank[current_status]:
                    raise RuntimeError("rehearsal transaction status cannot regress")
                existing_slot = entry.get("slot")
                if (
                    existing_slot is not None
                    and slot is not None
                    and int(existing_slot) != int(slot)
                ):
                    raise RuntimeError("rehearsal transaction finalized slot changed")
                if status_rank[status] == status_rank[current_status]:
                    return
                entry["status"] = status
                entry["slot"] = int(slot) if slot is not None else None
                entry["final_metadata"] = _json_value(metadata)
                _atomic_write(self.path, self._state)

    def record_terminal_transaction(
        self,
        signature: str,
        status: str,
        metadata: dict[str, Any],
    ) -> None:
        """Freeze a definitive failed/expired attempt without erasing it."""
        if status not in {"expired", "failed"}:
            raise RuntimeError("terminal rehearsal status must be expired or failed")
        frozen_metadata = _json_value(metadata)
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                entry = next(
                    (
                        item
                        for item in self._state["transactions"]
                        if item["signature"] == signature
                    ),
                    None,
                )
                if entry is None:
                    raise RuntimeError(
                        f"terminal signature {signature} has no protected-account preflight"
                    )
                prepared_fingerprint = entry.get("prepared_fingerprint")
                if (
                    prepared_fingerprint is None
                    or prepared_fingerprint != self._prepared_fingerprint(entry)
                ):
                    raise RuntimeError("prepared signature evidence changed on resume")
                current = str(entry.get("status") or "")
                if current in {"confirmed", "finalized"}:
                    raise RuntimeError(
                        "confirmed/finalized rehearsal transaction cannot become terminal"
                    )
                if current in {"expired", "failed"}:
                    if current != status or entry.get("terminal_metadata") != frozen_metadata:
                        raise RuntimeError("terminal rehearsal evidence changed on resume")
                    return
                if current != "prepared":
                    raise RuntimeError("rehearsal transaction status is invalid")
                entry["status"] = status
                entry["terminal_metadata"] = frozen_metadata
                _atomic_write(self.path, self._state)

    async def reconcile_signature(self, signature: str) -> int:
        parsed = Signature.from_string(signature)
        status = None
        async with AsyncClient(self.rpc_url, commitment=Finalized) as client:
            for _ in range(40):
                response = await client.get_signature_statuses(
                    [parsed],
                    search_transaction_history=True,
                )
                status = response.value[0] if response.value else None
                if status is not None and status.err is not None:
                    self.record_terminal_transaction(
                        signature,
                        "failed",
                        {"error": str(status.err), "source": "finalized_recovery"},
                    )
                    raise RuntimeError(
                        f"signature {signature} finalized with error: {status.err}"
                    )
                commitment = str(
                    getattr(status, "confirmation_status", "")
                ).lower()
                if status is not None and "finalized" in commitment:
                    break
                await asyncio.sleep(1.5)
        if status is None or "finalized" not in str(
            getattr(status, "confirmation_status", "")
        ).lower():
            raise RuntimeError(f"signature {signature} is not finalized yet")
        slot = int(status.slot)
        self.record_finalized_transaction(signature, slot, "finalized", {})
        return slot

    async def reconcile_prepared_transaction(self, entry: dict[str, Any]) -> None:
        """Resolve one prepared/confirmed row without guessing unknown state."""
        signature = str(entry.get("signature") or "")
        metadata = entry.get("metadata") or {}
        recent_blockhash = str(metadata.get("recent_blockhash") or "")
        last_valid = metadata.get("last_valid_block_height")
        if not signature or not recent_blockhash or isinstance(last_valid, bool):
            raise RuntimeError(
                "prepared rehearsal transaction lacks blockhash expiry evidence"
            )
        try:
            last_valid_height = int(last_valid)
            parsed_blockhash = Hash.from_string(recent_blockhash)
            parsed_signature = Signature.from_string(signature)
        except (TypeError, ValueError) as exc:
            raise RuntimeError("prepared rehearsal expiry identity is malformed") from exc
        async with AsyncClient(self.rpc_url, commitment=Finalized) as client:
            response = await client.get_signature_statuses(
                [parsed_signature], search_transaction_history=True
            )
            status = response.value[0] if response.value else None
            if status is not None:
                if status.err is not None:
                    self.record_terminal_transaction(
                        signature,
                        "failed",
                        {"error": str(status.err), "source": "resume_status"},
                    )
                    return
                commitment = str(getattr(status, "confirmation_status", "")).lower()
                if "finalized" in commitment:
                    self.record_finalized_transaction(
                        signature, int(status.slot), "finalized", {}
                    )
                    return
                raise RuntimeError(
                    f"signature {signature} exists but is not finalized; retry later"
                )
            block_height = int(
                (await client.get_block_height(commitment=Finalized)).value
            )
            valid = bool(
                (
                    await is_blockhash_valid_compat(
                        client, parsed_blockhash, commitment=Finalized
                    )
                ).value
            )
        if block_height > last_valid_height and not valid:
            self.record_terminal_transaction(
                signature,
                "expired",
                {
                    "source": "resume_expiry_proof",
                    "finalized_block_height": block_height,
                    "last_valid_block_height": last_valid_height,
                    "recent_blockhash": recent_blockhash,
                },
            )
            return
        raise RuntimeError(
            f"signature {signature} is absent but its blockhash may still be valid; retry later"
        )

    async def reconcile_prepared_transactions(self) -> None:
        """Recover finalized submissions whose process died before evidence finalization."""
        self._reload_current_state()
        pending_finality = [
            dict(item)
            for item in self._state.get("transactions", [])
            if item.get("status") in {"prepared", "confirmed"}
            and item.get("signature")
        ]
        for entry in pending_finality:
            await self.reconcile_prepared_transaction(entry)

    def _last_transaction_cursor(self) -> int:
        transactions = list(self._state.get("transactions", ()))
        prior = 0
        for reconciliation in self._state.get("reconciliations", ()):
            raw_cursor = reconciliation.get("transaction_cursor")
            if raw_cursor is None:
                signatures = [
                    str(value)
                    for value in reconciliation.get("transaction_signatures", ())
                ]
                indices = [
                    index
                    for index, item in enumerate(transactions)
                    if str(item.get("signature") or "") in signatures
                ]
                raw_cursor = max(indices, default=prior - 1) + 1
            if isinstance(raw_cursor, bool):
                raise RuntimeError("rehearsal transaction cursor is invalid")
            cursor = int(raw_cursor)
            if cursor < prior or cursor > len(transactions):
                raise RuntimeError("rehearsal transaction cursor changed or regressed")
            fingerprints = list(reconciliation.get("transaction_fingerprints", ()))
            signatures = list(reconciliation.get("transaction_signatures", ()))
            if fingerprints and len(fingerprints) != len(signatures):
                raise RuntimeError("rehearsal transaction fingerprint boundary is malformed")
            for signature, fingerprint in zip(signatures, fingerprints):
                entry = next(
                    (
                        item
                        for item in transactions[:cursor]
                        if str(item.get("signature") or "") == str(signature)
                    ),
                    None,
                )
                if entry is None or self._prepared_fingerprint(entry) != fingerprint:
                    raise RuntimeError(
                        "rehearsal reconciliation transaction fingerprint changed"
                    )
            prior = cursor
        return prior

    def _unreconciled_transaction_suffix(self) -> list[dict[str, Any]]:
        transactions = list(self._state.get("transactions", ()))
        suffix = transactions[self._last_transaction_cursor() :]
        for item in suffix:
            status = str(item.get("status") or "")
            if status not in {
                "expired",
                "failed",
                "prepared",
                "confirmed",
                "finalized",
            }:
                raise RuntimeError("rehearsal transaction status is invalid")
        return suffix

    def _unclaimed_finalized_transactions(self) -> list[dict[str, Any]]:
        return [
            item
            for item in self._unreconciled_transaction_suffix()
            if item.get("status") == "finalized"
        ]

    def _credit_recovery_stage(self, transaction: dict[str, Any]) -> str:
        account_set = set(transaction.get("account_set") or ())
        dynamic = self._state.get("dynamic_rehearsal_addresses") or {}
        matches = [
            stage
            for label, stage in (
                ("rehearsal_vault_funding_cal_receipt", "vault_funding"),
                (
                    "rehearsal_completion_cal_receipt",
                    "receipt_backed_completion",
                ),
                (
                    "rehearsal_stake_cal_top_up_cal_receipt",
                    "stake_cal_top_up",
                ),
            )
            if dynamic.get(label) in account_set
        ]
        if len(matches) != 1:
            raise RuntimeError(
                "finalized credit_cal transaction does not bind one recovery stage"
            )
        return matches[0]

    def _recoverable_loop_stage(
        self, transactions: list[dict[str, Any]]
    ) -> str | None:
        terminal_events: list[tuple[str, str]] = []
        for transaction in transactions:
            names = [
                str(instruction["instruction_name"])
                for instruction in transaction.get("instruction_order", ())
                if instruction.get("instruction_name")
            ]
            name_set = set(names)
            tx_type = str((transaction.get("metadata") or {}).get("tx_type") or "")
            stage: str | None = None
            if "credit_cal" in name_set:
                stage = self._credit_recovery_stage(transaction)
            elif "create_vault_with_usdc" in name_set:
                stage = "create_vault_with_usdc"
            elif "admin_override_open_settlement_week" in name_set:
                stage = "override_settlement_week"
            elif "stake_cal_in_vault" in name_set:
                stage = "stake_cal"
            elif "admin_override_stake_eligibility" in name_set:
                stage = "override_stake_eligibility"
            elif "distribute_epoch_rewards" in name_set:
                stage = "distribute_epoch_rewards"
            elif {
                "collect_stake_rewards_for",
                "unstake_cal_from_vault",
            }.issubset(name_set):
                stage = "collect_then_unstake"
            elif name_set == {"collect_stake_rewards_for"}:
                stage = "legacy_withdrawn_harvest"
            elif tx_type in {
                "settlement_recipient_ata_prepare",
                "settlement_lookup_table_create",
                "settlement_lookup_table_extend",
            }:
                stage = "settlement_transport_ready"
            if stage is not None:
                terminal_events.append((str(transaction.get("signature")), stage))

        if not terminal_events:
            return None
        stages = {stage for _, stage in terminal_events}
        transport_only = stages == {"settlement_transport_ready"}
        if len(stages) != 1 or (len(terminal_events) != 1 and not transport_only):
            detail = ", ".join(f"{signature}:{stage}" for signature, stage in terminal_events)
            raise RuntimeError(
                "multiple unreconciled finalized loop boundaries are ambiguous: " + detail
            )
        target = terminal_events[-1][1]
        allowed_names = {
            "vault_funding": {"record_ride", "credit_cal"},
            "receipt_backed_completion": {
                "admin_seed_pending_rewards",
                "record_ride",
                "record_climb_completion_v2",
                "credit_cal",
            },
            "stake_cal_top_up": {"record_ride", "credit_cal"},
            "create_vault_with_usdc": {"create_vault_with_usdc"},
            "override_settlement_week": {"admin_override_open_settlement_week"},
            "stake_cal": {"stake_cal_in_vault"},
            "override_stake_eligibility": {"admin_override_stake_eligibility"},
            "settlement_transport_ready": set(),
            "distribute_epoch_rewards": {"distribute_epoch_rewards"},
            "collect_then_unstake": {
                "collect_stake_rewards_for",
                "unstake_cal_from_vault",
            },
            "legacy_withdrawn_harvest": {"collect_stake_rewards_for"},
        }[target]
        transport_types = {
            "settlement_recipient_ata_prepare",
            "settlement_lookup_table_create",
            "settlement_lookup_table_extend",
        }
        for transaction in transactions:
            names = {
                str(instruction["instruction_name"])
                for instruction in transaction.get("instruction_order", ())
                if instruction.get("instruction_name")
            }
            tx_type = str((transaction.get("metadata") or {}).get("tx_type") or "")
            valid = (
                names.issubset(allowed_names)
                and bool(names)
                if target != "settlement_transport_ready"
                else not names and tx_type in transport_types
            )
            if not valid:
                raise RuntimeError(
                    "unreconciled finalized transaction suffix does not match "
                    f"the exact {target} boundary"
                )
        return target

    @staticmethod
    def _validate_stake_eligibility_transaction(
        transactions: list[dict[str, Any]],
        identity: dict[str, Any],
    ) -> int:
        if len(transactions) != 1 or transactions[0].get("status") != "finalized":
            raise RuntimeError(
                "stake eligibility transaction evidence must contain exactly one "
                "finalized transaction"
            )
        instructions = [
            instruction
            for instruction in transactions[0].get("instruction_order", ())
            if instruction.get("instruction_name")
            == "admin_override_stake_eligibility"
        ]
        if len(instructions) != 1:
            raise RuntimeError(
                "stake eligibility transaction evidence must contain exactly one "
                "override instruction"
            )
        instruction = instructions[0]
        expected_discriminator = _discriminator(
            "admin_override_stake_eligibility"
        )
        try:
            data = bytes.fromhex(str(instruction.get("data_hex") or ""))
        except ValueError as exc:
            raise RuntimeError(
                "stake eligibility transaction payload is not valid hex"
            ) from exc
        if (
            str(instruction.get("program_id") or "")
            != str(identity["program_id"])
            or len(data) != 16
            or data[:8] != expected_discriminator
            or int(instruction.get("data_len", -1)) != len(data)
            or str(instruction.get("data_sha256") or "")
            != hashlib.sha256(data).hexdigest()
        ):
            raise RuntimeError(
                "stake eligibility transaction program or payload is not exact"
            )
        settlement_week = struct.unpack_from("<Q", data, 8)[0]
        if settlement_week != int(identity["settlement_week"]):
            raise RuntimeError(
                "stake eligibility transaction does not bind the frozen Settlement Week"
            )
        return settlement_week

    async def recover_one_loop_stage(self) -> str | None:
        """Capture exactly one finalized-but-unreconciled application boundary."""
        self._reload_current_state()
        transactions = self._unclaimed_finalized_transactions()
        stage = self._recoverable_loop_stage(transactions)
        if stage is None:
            return None
        if self.has_reconciliation(stage):
            raise RuntimeError(
                f"finalized {stage} transaction is not bound to its existing reconciliation"
            )
        if stage == "settlement_transport_ready":
            # The manager must re-enter its deterministic get/plan/ready flow
            # and prove the finalized ALT plus recipient accounts first.
            return stage
        await self.capture_reconciliation(stage)
        return stage

    @staticmethod
    def _numeric(
        snapshot: dict[str, dict[str, Any]],
        label: str,
        field: str,
        *,
        required: bool = True,
    ) -> int:
        item = snapshot.get(label) or {}
        if not item.get("exists"):
            if required:
                raise RuntimeError(
                    f"rehearsal reconciliation requires existing {label}"
                )
            return 0
        decoded = item.get("decoded") or {}
        value = decoded.get(field)
        if value is None:
            parts = field.split("_")
            camel = parts[0] + "".join(part.capitalize() for part in parts[1:])
            value = _field_value(decoded.get("fields") or {}, field, camel)
        try:
            return int(value)
        except (TypeError, ValueError) as exc:
            raise RuntimeError(
                f"rehearsal reconciliation cannot decode {label}.{field}"
            ) from exc

    @classmethod
    def _delta(
        cls,
        before: dict[str, dict[str, Any]],
        after: dict[str, dict[str, Any]],
        label: str,
        field: str,
        *,
        before_required: bool = True,
    ) -> int:
        return cls._numeric(after, label, field) - cls._numeric(
            before, label, field, required=before_required
        )

    @classmethod
    def _validate_economic_reconciliation(
        cls,
        stage: str,
        *,
        baseline: dict[str, dict[str, Any]],
        previous: dict[str, dict[str, Any]],
        current: dict[str, dict[str, Any]],
        identity: dict[str, Any],
    ) -> dict[str, Any]:
        """Fail closed on conservation statements at each durable boundary."""
        result: dict[str, Any] = {"validated": True, "stage": stage}
        if stage in {"vault_funding", "stake_cal_top_up"}:
            amount = int(identity["user_cal"])
            cal_balance_delta = cls._delta(
                previous, current, "rehearsal_user_cal_ata", "amount_base_units"
            )
            cal_supply_delta = cls._delta(
                previous, current, "rehearsal_cal_mint", "supply_base_units"
            )
            cumulative_balance = cls._delta(
                baseline, current, "rehearsal_user_cal_ata", "amount_base_units"
            )
            cumulative_supply = cls._delta(
                baseline, current, "rehearsal_cal_mint", "supply_base_units"
            )
            if (cal_balance_delta, cal_supply_delta) not in {
                (amount, amount),
                (0, 0),
            } or (cal_balance_delta == 0 and cumulative_balance < amount):
                raise RuntimeError("deterministic rehearsal CAL funding does not reconcile")
            if cumulative_balance != cumulative_supply:
                raise RuntimeError("rehearsal CAL funding balance/supply diverged")
            result.update(
                {
                    "cal_funding_delta": cal_balance_delta,
                    "cal_supply_delta": cal_supply_delta,
                }
            )

        elif stage == "create_vault_with_usdc":
            usdc_cost = int(identity["vault_creation_usdc"])
            cal_cost = int(
                identity.get("vault_creation_cal_base_units")
                or int(identity["vault_creation_cal"]) * 1_000_000_000
            )
            usdc_user = cls._delta(
                previous, current, "rehearsal_user_usdc_ata", "amount_base_units"
            )
            usdc_treasury = cls._delta(
                previous, current, "rehearsal_usdc_treasury", "amount_base_units"
            )
            if usdc_user != -usdc_cost or usdc_treasury != usdc_cost:
                raise RuntimeError(
                    "rehearsal USDC creation cost does not reconcile between rider and treasury"
                )
            if cls._delta(
                previous, current, "rehearsal_usdc_mint", "supply_base_units"
            ) != 0:
                raise RuntimeError("rehearsal USDC supply changed during Vault creation")
            if cls._delta(
                previous, current, "rehearsal_user_cal_ata", "amount_base_units"
            ) != -cal_cost or cls._delta(
                previous, current, "rehearsal_cal_mint", "supply_base_units"
            ) != -cal_cost:
                raise RuntimeError("rehearsal CAL Vault-creation burn does not reconcile")
            counter_delta = cls._delta(
                previous, current, "rehearsal_vault_counter", "count"
            )
            if counter_delta != 1:
                raise RuntimeError("rehearsal VaultCounter did not advance exactly once")
            for label in (
                "rehearsal_expected_vault",
                "rehearsal_vault_activation",
                "rehearsal_record_board",
                "rehearsal_local_legend",
            ):
                if not (current.get(label) or {}).get("exists"):
                    raise RuntimeError(f"Vault creation is missing expected {label}")
            result.update(
                {"usdc_cost": usdc_cost, "cal_burn_base_units": cal_cost}
            )

        elif stage == "receipt_backed_completion":
            for label in (
                "rehearsal_completion_ride_attestation",
                "rehearsal_completion_tribute_budget",
                "rehearsal_completion_cal_receipt",
                "rehearsal_completion_receipt",
                "rehearsal_vault_completion",
            ):
                if not (current.get(label) or {}).get("exists"):
                    raise RuntimeError(
                        f"receipt-backed stage is missing expected {label}"
                    )
            cal_amount = int(identity["vault_alloc_cal"])
            from smoke_devnet_economics import measured_smoke_cal_tribute, SMOKE_COMPLETION_TIME_S
            tribute = measured_smoke_cal_tribute(cal_amount, SMOKE_COMPLETION_TIME_S)
            cal_balance = cls._delta(
                previous, current, "rehearsal_user_cal_ata", "amount_base_units"
            )
            cal_supply = cls._delta(
                previous, current, "rehearsal_cal_mint", "supply_base_units"
            )
            if cal_balance != cal_amount or cal_supply != cal_amount:
                raise RuntimeError("receipt-backed CAL mint does not reconcile")
            if cls._delta(
                previous, current, "rehearsal_expected_vault", "total_cal_burned"
            ) != tribute:
                raise RuntimeError("receipt-backed Vault CAL tribute does not reconcile")
            if cls._numeric(
                current,
                "rehearsal_completion_tribute_budget",
                "total_cal_tributed",
            ) != tribute or cls._numeric(
                current,
                "rehearsal_completion_cal_receipt",
                "amount",
            ) != cal_amount:
                raise RuntimeError("receipt-backed CAL budget/receipt does not reconcile")
            if cls._numeric(
                current, "rehearsal_vault_completion", "total_cal_tributed"
            ) != tribute:
                raise RuntimeError("VaultCompletion tribute does not reconcile")
            result.update(
                {"cal_minted": cal_amount, "cal_tribute_recorded": tribute}
            )

        elif stage == "stake_cal":
            stake_cal = int(identity["stake_cal"])
            rider_cal_delta = cls._delta(
                previous, current, "rehearsal_user_cal_ata", "amount_base_units"
            )
            escrow_delta = cls._delta(
                previous,
                current,
                "rehearsal_cal_escrow",
                "amount_base_units",
                before_required=False,
            )
            cal_supply_delta = cls._delta(
                previous, current, "rehearsal_cal_mint", "supply_base_units"
            )
            if (
                rider_cal_delta != -stake_cal
                or escrow_delta != stake_cal
                or cal_supply_delta != 0
            ):
                raise RuntimeError("rehearsal CAL stake transfer does not reconcile")
            stake_fields = _decoded_fields(
                current.get("rehearsal_vault_stake") or {}
            )
            stake_user = str(_field_value(stake_fields, "user", default=""))
            stake_vault_id = int(
                _field_value(stake_fields, "vault_id", "vaultId", default=-1)
            )
            stake_cal_current = cls._numeric(
                current, "rehearsal_vault_stake", "cal_staked"
            )
            stake_lp_current = cls._numeric(
                current, "rehearsal_vault_stake", "lp_tokens"
            )
            if (
                stake_user != str(identity["user"])
                or stake_vault_id != int(identity["vault_id"])
                or stake_cal_current != stake_cal
                or stake_lp_current != stake_cal
            ):
                raise RuntimeError("rehearsal stake account does not hold the exact CAL/LP")
            lp_supply = cls._numeric(
                current, "rehearsal_vault_lp_mint", "supply_base_units"
            )
            position_lp = cls._numeric(
                current, "rehearsal_position_lp", "amount_base_units"
            )
            if lp_supply != stake_lp_current or position_lp != stake_lp_current:
                raise RuntimeError("rehearsal LP supply/custody does not reconcile")
            result.update(
                {
                    "cal_staked": stake_cal_current,
                    "lp_minted": stake_lp_current,
                    "cal_supply_delta": cal_supply_delta,
                }
            )

        elif stage == "ordinary_week_open":
            vault = _decoded_fields(current.get("rehearsal_expected_vault") or {})
            stake = _decoded_fields(current.get("rehearsal_vault_stake") or {})
            week = int(identity["settlement_week"])
            pending_week = int(_field_value(stake, "pending_effective_week_plus_one", "pendingEffectiveWeekPlusOne", default=0))
            effective_lp = int(_field_value(stake, "effective_lp_tokens", "effectiveLpTokens", default=0))
            pending_lp = int(_field_value(stake, "pending_lp_tokens", "pendingLpTokens", default=0))
            if (int(_field_value(vault, "id", default=-1)) != int(identity["vault_id"])
                or int(_field_value(vault, "open_settlement_week", "openSettlementWeek", default=-1)) != week
                or str(_field_value(stake, "user", default="")) != str(identity["user"])
                or int(_field_value(stake, "vault_id", "vaultId", default=-1)) != int(identity["vault_id"])
                or not (effective_lp > 0 or (pending_lp > 0 and 0 < pending_week <= week + 1))):
                raise RuntimeError("ordinary settlement did not establish the frozen eligible position")
            if cls._delta(previous, current, "rehearsal_dung_mint", "supply_base_units") != 0:
                raise RuntimeError("quiet-week catchup unexpectedly minted DUNG")
            result["settlement_week"] = week

        elif stage == "override_stake_eligibility":
            previous_fields = _decoded_fields(
                previous.get("rehearsal_vault_stake") or {}
            )
            stake_fields = _decoded_fields(
                current.get("rehearsal_vault_stake") or {}
            )
            expected_user = str(identity["user"])
            expected_vault_id = int(identity["vault_id"])
            expected_week = int(identity["settlement_week"])
            if (
                str(_field_value(stake_fields, "user", default=""))
                != expected_user
                or int(
                    _field_value(
                        stake_fields, "vault_id", "vaultId", default=-1
                    )
                )
                != expected_vault_id
            ):
                raise RuntimeError(
                    "rehearsal VaultStake rider/vault identity changed during eligibility"
                )
            previous_vault_fields = _decoded_fields(
                previous.get("rehearsal_expected_vault") or {}
            )
            vault_fields = _decoded_fields(
                current.get("rehearsal_expected_vault") or {}
            )
            previous_vault_id = int(
                _field_value(previous_vault_fields, "id", default=-1)
            )
            vault_id = int(_field_value(vault_fields, "id", default=-1))
            previous_open_week = int(
                _field_value(
                    previous_vault_fields,
                    "open_settlement_week",
                    "openSettlementWeek",
                    default=-1,
                )
            )
            open_week = int(
                _field_value(
                    vault_fields,
                    "open_settlement_week",
                    "openSettlementWeek",
                    default=-1,
                )
            )
            if (
                previous_vault_id != expected_vault_id
                or vault_id != expected_vault_id
                or previous_open_week != expected_week
                or open_week != expected_week
            ):
                raise RuntimeError(
                    "rehearsal Vault Settlement Week changed during eligibility"
                )
            unchanged_fields = (
                "cal_staked",
                "lp_tokens",
                "staked_at",
                "rewards_earned",
                "bump",
            )
            changed = [
                field
                for field in unchanged_fields
                if _field_value(stake_fields, field)
                != _field_value(previous_fields, field)
            ]
            if changed:
                raise RuntimeError(
                    "rehearsal VaultStake changed immutable eligibility fields: "
                    + ", ".join(changed)
                )
            lp_tokens = int(
                _field_value(stake_fields, "lp_tokens", "lpTokens", default=-1)
            )
            effective_lp = int(
                _field_value(
                    stake_fields,
                    "effective_lp_tokens",
                    "effectiveLpTokens",
                    default=-1,
                )
            )
            pending_lp = int(
                _field_value(
                    stake_fields,
                    "pending_lp_tokens",
                    "pendingLpTokens",
                    default=-1,
                )
            )
            pending_week_plus_one = int(
                _field_value(
                    stake_fields,
                    "pending_effective_week_plus_one",
                    "pendingEffectiveWeekPlusOne",
                    default=-1,
                )
            )
            if (
                lp_tokens <= 0
                or effective_lp != lp_tokens
                or pending_lp != 0
                or pending_week_plus_one != 0
            ):
                raise RuntimeError(
                    "rehearsal VaultStake eligibility snapshot did not become fully effective"
                )
            result.update(
                {
                    "open_settlement_week": open_week,
                    "effective_lp_tokens": effective_lp,
                    "pending_lp_tokens": pending_lp,
                    "pending_effective_week_plus_one": pending_week_plus_one,
                }
            )

        elif stage == "distribute_epoch_rewards":
            for label in (
                "rehearsal_dung_mint_state",
                "rehearsal_dung_pol",
                "rehearsal_dung_treasury",
                "rehearsal_vault_stake",
            ):
                if not (current.get(label) or {}).get("exists"):
                    raise RuntimeError(
                        f"DUNG distribution is missing expected {label}"
                    )
            minted = cls._delta(
                previous, current, "rehearsal_dung_mint", "supply_base_units"
            )
            pol = cls._delta(
                previous, current, "rehearsal_dung_pol", "amount_base_units"
            )
            treasury = cls._delta(
                previous, current, "rehearsal_dung_treasury", "amount_base_units"
            )
            rewards = cls._numeric(
                current, "rehearsal_vault_stake", "rewards_earned"
            )
            rider = cls._delta(
                previous,
                current,
                "rehearsal_user_dung_ata",
                "amount_base_units",
                before_required=False,
            )
            if minted != pol + treasury + rider or rewards <= 0:
                raise RuntimeError("rehearsal DUNG distribution deltas do not reconcile")
            state_minted = cls._delta(
                previous, current, "rehearsal_dung_mint_state", "total_minted"
            )
            reserved = cls._delta(
                previous,
                current,
                "rehearsal_dung_mint_state",
                "community_reserved",
            )
            if state_minted != minted or reserved < rewards:
                raise RuntimeError("rehearsal DungMintState distribution does not reconcile")
            result.update(
                {
                    "dung_minted_now": minted,
                    "pol_delta": pol,
                    "treasury_distribution_delta": treasury,
                    "rider_direct_distribution_delta": rider,
                    "reserved_staker_rewards": rewards,
                }
            )

        elif stage in {"collect_then_unstake", "legacy_withdrawn_harvest"}:
            for label in (
                "rehearsal_vault_stake",
                "rehearsal_vault_lp_mint",
                "rehearsal_position_lp",
                "rehearsal_cal_escrow",
                "rehearsal_expected_vault",
            ):
                if not (current.get(label) or {}).get("exists"):
                    raise RuntimeError(f"final cleanup is missing expected {label}")
            zero_values = {
                "stake_cal": cls._numeric(
                    current, "rehearsal_vault_stake", "cal_staked"
                ),
                "stake_lp": cls._numeric(
                    current, "rehearsal_vault_stake", "lp_tokens"
                ),
                "uncollected_rewards": cls._numeric(
                    current, "rehearsal_vault_stake", "rewards_earned"
                ),
                "lp_supply": cls._numeric(
                    current, "rehearsal_vault_lp_mint", "supply_base_units"
                ),
                "position_lp": cls._numeric(
                    current, "rehearsal_position_lp", "amount_base_units"
                ),
                "cal_escrow": cls._numeric(
                    current, "rehearsal_cal_escrow", "amount_base_units"
                ),
                "vault_total_cal": cls._numeric(
                    current, "rehearsal_expected_vault", "total_cal_staked"
                ),
            }
            if any(zero_values.values()):
                raise RuntimeError(
                    "rehearsal did not reach zero final LP/stake/uncollected rewards"
                )
            rewards_before = cls._numeric(
                previous, "rehearsal_vault_stake", "rewards_earned"
            )
            if rewards_before > 0:
                rider_dung = cls._delta(
                    previous,
                    current,
                    "rehearsal_user_dung_ata",
                    "amount_base_units",
                )
                treasury_dung = cls._delta(
                    previous,
                    current,
                    "rehearsal_dung_treasury",
                    "amount_base_units",
                )
                fee = rewards_before * int(identity["harvest_fee_bps"]) // 10_000
                if rider_dung != rewards_before - fee or treasury_dung != fee:
                    raise RuntimeError(
                        "rehearsal DUNG rider/harvest-fee deltas do not reconcile"
                    )
                if cls._delta(
                    previous,
                    current,
                    "rehearsal_dung_mint",
                    "supply_base_units",
                ) != rewards_before or cls._delta(
                    previous,
                    current,
                    "rehearsal_dung_mint_state",
                    "total_minted",
                ) != rewards_before or cls._delta(
                    previous,
                    current,
                    "rehearsal_dung_mint_state",
                    "community_reserved",
                ) != -rewards_before:
                    raise RuntimeError(
                        "rehearsal DUNG supply/reservation collection does not reconcile"
                    )
            prior_escrow = cls._numeric(
                previous, "rehearsal_cal_escrow", "amount_base_units"
            )
            if prior_escrow > 0:
                exit_fee = prior_escrow * 50 // 10_000
                cal_returned = cls._delta(
                    previous,
                    current,
                    "rehearsal_user_cal_ata",
                    "amount_base_units",
                )
                cal_burned = -cls._delta(
                    previous, current, "rehearsal_cal_mint", "supply_base_units"
                )
                if cal_returned != prior_escrow - exit_fee or cal_burned != exit_fee:
                    raise RuntimeError(
                        "rehearsal CAL return/exit-fee deltas do not reconcile"
                    )
            result["final_zero_state"] = zero_values

        if stage == "economic_loop_complete":
            for label in (
                "rehearsal_completion_ride_attestation",
                "rehearsal_completion_tribute_budget",
                "rehearsal_completion_cal_receipt",
                "rehearsal_completion_receipt",
                "rehearsal_vault_completion",
            ):
                if not (current.get(label) or {}).get("exists"):
                    raise RuntimeError(
                        f"receipt-backed stage is missing expected {label}"
                    )
            final_zero = {
                "stake_cal": cls._numeric(
                    current, "rehearsal_vault_stake", "cal_staked"
                ),
                "stake_lp": cls._numeric(
                    current, "rehearsal_vault_stake", "lp_tokens"
                ),
                "uncollected_rewards": cls._numeric(
                    current, "rehearsal_vault_stake", "rewards_earned"
                ),
                "lp_supply": cls._numeric(
                    current, "rehearsal_vault_lp_mint", "supply_base_units"
                ),
                "position_lp": cls._numeric(
                    current, "rehearsal_position_lp", "amount_base_units"
                ),
                "cal_escrow": cls._numeric(
                    current, "rehearsal_cal_escrow", "amount_base_units"
                ),
                "vault_total_cal": cls._numeric(
                    current, "rehearsal_expected_vault", "total_cal_staked"
                ),
            }
            if any(final_zero.values()):
                raise RuntimeError(
                    "economic loop final evidence has nonzero LP/stake/rewards state"
                )
            if cls._delta(
                baseline,
                current,
                "rehearsal_usdc_mint",
                "supply_base_units",
            ) != 0:
                raise RuntimeError("economic loop changed the fixed rehearsal USDC supply")
            result["final_zero_state"] = final_zero
        return result

    async def capture_reconciliation(self, stage: str) -> None:
        self._reload_current_state()
        suffix = self._unreconciled_transaction_suffix()
        unresolved = [
            str(item.get("signature") or "")
            for item in suffix
            if item.get("status") not in {"finalized", "expired", "failed"}
        ]
        if unresolved:
            raise RuntimeError(
                "rehearsal stage cannot reconcile unknown transaction status: "
                + ", ".join(unresolved)
            )
        finalized_suffix = [
            item for item in suffix if item.get("status") == "finalized"
        ]
        classified = self._recoverable_loop_stage(finalized_suffix)
        if classified is not None and classified != stage:
            raise RuntimeError(
                f"finalized transaction suffix belongs to {classified}, not {stage}"
            )
        if classified is None and finalized_suffix:
            raise RuntimeError(
                f"finalized transaction suffix cannot prove the {stage} boundary"
            )
        protected_addresses = {
            label: Pubkey.from_string(address)
            for label, address in self._state["protected_addresses"].items()
        }
        identity = self._state["identity"]
        rehearsal_addresses = self._current_rehearsal_addresses()
        protected_slot, protected = await self._read_accounts(
            self.rpc_url,
            protected_addresses,
        )
        rehearsal_slot, rehearsal = await self._read_accounts(
            self.rpc_url,
            rehearsal_addresses,
        )
        self._assert_protected_baseline(
            self._state["baseline"]["protected"],
            protected,
        )
        self._validate_rehearsal_authorities(rehearsal, identity)
        matching = [
            (index, item)
            for index, item in enumerate(self._state.get("reconciliations", ()))
            if item.get("stage") == stage
        ]
        if matching and stage != "receipt_backed_completion":
            if len(matching) != 1:
                raise RuntimeError(f"{stage} reconciliation is duplicated")
            if finalized_suffix:
                raise RuntimeError(
                    f"finalized {stage} transaction is not bound to its existing reconciliation"
                )
            return
        if stage == "receipt_backed_completion" and matching:
            if len(matching) != 1:
                raise RuntimeError(
                    "receipt-backed completion reconciliation is duplicated"
                )
            if finalized_suffix:
                raise RuntimeError(
                    "duplicate finalized receipt-backed completion transaction"
                )
            index, frozen = matching[0]
            predecessor = (
                self._state["reconciliations"][index - 1]["rehearsal"]
                if index > 0
                else self._state["baseline"]["rehearsal"]
            )
            recomputed = self._validate_economic_reconciliation(
                stage,
                baseline=self._state["baseline"]["rehearsal"],
                previous=predecessor,
                current=frozen.get("rehearsal") or {},
                identity=identity,
            )
            if frozen.get("economic_checks") != recomputed:
                raise RuntimeError(
                    "frozen receipt-backed completion economic evidence changed"
                )
            immutable_receipts = (
                "rehearsal_completion_ride_attestation",
                "rehearsal_completion_tribute_budget",
                "rehearsal_completion_cal_receipt",
                "rehearsal_completion_receipt",
                "rehearsal_vault_completion",
            )
            frozen_accounts = frozen.get("rehearsal") or {}
            changed = [
                label
                for label in immutable_receipts
                if self._fingerprint(frozen_accounts.get(label) or {})
                != self._fingerprint(rehearsal.get(label) or {})
            ]
            if changed:
                raise RuntimeError(
                    "frozen receipt-backed completion account evidence changed: "
                    + ", ".join(changed)
                )
            return
        previous = (
            self._state["reconciliations"][-1]["rehearsal"]
            if self._state.get("reconciliations")
            else self._state["baseline"]["rehearsal"]
        )
        eligibility_week_argument = (
            self._validate_stake_eligibility_transaction(
                finalized_suffix,
                identity,
            )
            if stage == "override_stake_eligibility"
            else None
        )
        economic_checks = self._validate_economic_reconciliation(
            stage,
            baseline=self._state["baseline"]["rehearsal"],
            previous=previous,
            current=rehearsal,
            identity=identity,
        )
        if eligibility_week_argument is not None:
            economic_checks["settlement_week_argument"] = eligibility_week_argument
        transport_checks = (
            self.validate_settlement_transport_snapshot(rehearsal)
            if stage == "settlement_transport_ready"
            else None
        )
        transaction_signatures = [str(item["signature"]) for item in finalized_suffix]
        transaction_fingerprints = [
            self._prepared_fingerprint(item) for item in finalized_suffix
        ]
        transaction_cursor = len(self._state.get("transactions", ()))
        with self._lock:
            with self._write_lock():
                self._reload_current_state()
                self._state["reconciliations"].append(
                    {
                        "stage": stage,
                        "protected_slot": protected_slot,
                        "rehearsal_slot": rehearsal_slot,
                        "protected": protected,
                        "rehearsal": rehearsal,
                        "economic_checks": economic_checks,
                        "transport_checks": transport_checks,
                        "transaction_signatures": transaction_signatures,
                        "transaction_fingerprints": transaction_fingerprints,
                        "transaction_cursor": transaction_cursor,
                    }
                )
                _atomic_write(self.path, self._state)

    async def finalize_stage(
        self,
        stage: str,
        signature: str | None = None,
    ) -> None:
        if signature and not signature.startswith("existing "):
            await self.reconcile_signature(signature)
        await self.reconcile_prepared_transactions()
        await self.capture_reconciliation(stage)
