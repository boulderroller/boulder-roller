"""Durable preparation and validation for atomic v0 settlement transactions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.address_lookup_table_account import (
    AddressLookupTable,
    AddressLookupTableAccount,
    ID as ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
    LOOKUP_TABLE_MAX_ADDRESSES,
    derive_lookup_table_address,
)
from solders.compute_budget import set_compute_unit_limit, set_compute_unit_price
from solders.hash import Hash
from solders.instruction import AccountMeta, Instruction
from solders.pubkey import Pubkey
from solders.system_program import ID as SYSTEM_PROGRAM_ID

from ..solana_direct import (
    DirectConfig,
    SettlementDistributionPlan,
    _account_data_bytes,
    _prepare_settlement_recipient_atas,
    _settlement_lookup_required_addresses,
    _unique_signers,
    _validate_settlement_lookup_table_state,
    resolve_backend_authority,
)
from .solana_submit import (
    PACKET_DATA_SIZE,
    _build_signed_transaction,
    _get_priority_fee,
    submit_and_confirm,
)


SETTLEMENT_TRANSPORT_VERSION = 0
SETTLEMENT_V0_REVIEW_LIMIT_BYTES = 900
LOOKUP_TABLE_EXTEND_CHUNK_SIZE = 20

TransportPlanCallback = Callable[[dict[str, Any]], Awaitable[None]]


class SettlementTransportError(RuntimeError):
    """Settlement transport preparation failed without economic mutation."""


class SettlementTransportPending(SettlementTransportError):
    """Finalized chain state has not caught up to idempotent preparation."""


class SettlementTransportStaleError(SettlementTransportError):
    """A frozen settlement transport no longer matches finalized account state."""


@dataclass(frozen=True)
class LookupTableGeneration:
    id: str
    vault_id: int
    program_id: str
    generation: int
    lookup_table_address: Pubkey
    authority: Pubkey
    recent_slot: int
    status: str
    create_tx_signature: Optional[str]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "LookupTableGeneration":
        return cls(
            id=str(row["id"]),
            vault_id=_exact_nonnegative_int(row["vault_id"], "vault_id"),
            program_id=str(row["program_id"]),
            generation=_exact_nonnegative_int(row["generation"], "generation"),
            lookup_table_address=Pubkey.from_string(str(row["lookup_table_address"])),
            authority=Pubkey.from_string(str(row["authority"])),
            recent_slot=_exact_nonnegative_int(row["recent_slot"], "recent_slot"),
            status=str(row["status"]),
            create_tx_signature=(
                str(row["create_tx_signature"])
                if row.get("create_tx_signature")
                else None
            ),
        )


def _exact_nonnegative_int(value: Any, field_name: str) -> int:
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name} must be an exact nonnegative integer")
    text = str(value)
    if not text.isascii() or not text.isdigit():
        raise ValueError(f"{field_name} must be an exact nonnegative integer")
    return int(text)


def _first_rpc_row(response: Any) -> dict[str, Any]:
    data = getattr(response, "data", None)
    if isinstance(data, list):
        data = data[0] if data else None
    if not isinstance(data, Mapping):
        raise SettlementTransportError("settlement transport RPC returned no row")
    return dict(data)


async def _rpc(db: Any, name: str, params: dict[str, Any]) -> Any:
    return await asyncio.to_thread(lambda: db.rpc(name, params).execute())


def _make_create_lookup_table_ix(
    *,
    authority: Pubkey,
    payer: Pubkey,
    recent_slot: int,
) -> tuple[Instruction, Pubkey]:
    address, bump = derive_lookup_table_address(authority, recent_slot)
    return (
        Instruction(
            program_id=ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
            accounts=[
                AccountMeta(address, is_signer=False, is_writable=True),
                AccountMeta(authority, is_signer=True, is_writable=False),
                AccountMeta(payer, is_signer=True, is_writable=True),
                AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
            ],
            data=struct.pack("<IQB", 0, recent_slot, bump),
        ),
        address,
    )


def _make_extend_lookup_table_ix(
    *,
    lookup_table: Pubkey,
    authority: Pubkey,
    payer: Pubkey,
    addresses: list[Pubkey],
) -> Instruction:
    if not 1 <= len(addresses) <= LOOKUP_TABLE_EXTEND_CHUNK_SIZE:
        raise ValueError("lookup-table extension must contain 1 to 20 addresses")
    return Instruction(
        program_id=ADDRESS_LOOKUP_TABLE_PROGRAM_ID,
        accounts=[
            AccountMeta(lookup_table, is_signer=False, is_writable=True),
            AccountMeta(authority, is_signer=True, is_writable=False),
            AccountMeta(payer, is_signer=True, is_writable=True),
            AccountMeta(SYSTEM_PROGRAM_ID, is_signer=False, is_writable=False),
        ],
        data=(
            struct.pack("<IQ", 2, len(addresses))
            + b"".join(bytes(address) for address in addresses)
        ),
    )


async def _fetch_lookup_table_state(
    config: DirectConfig,
    address: Pubkey,
) -> tuple[Optional[AddressLookupTable], int]:
    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        info = await client.get_account_info(address, commitment=Finalized)
        slot = await client.get_slot(commitment=Finalized)
    if info.value is None:
        return None, int(slot.value)
    if info.value.owner != ADDRESS_LOOKUP_TABLE_PROGRAM_ID:
        raise SettlementTransportError(
            f"settlement lookup table {address} owner mismatch"
        )
    try:
        state = AddressLookupTable.deserialize(_account_data_bytes(info.value.data))
    except Exception as exc:
        raise SettlementTransportError(
            f"settlement lookup table {address} failed to decode"
        ) from exc
    return state, int(slot.value)


def settlement_transport_manifest_sha256(
    *,
    program_id: Pubkey,
    vault_id: int,
    settlement_week: int,
    lookup_table: Pubkey,
    lookup_table_generation: int,
    instruction: Instruction,
) -> str:
    payload = {
        "transaction_version": SETTLEMENT_TRANSPORT_VERSION,
        "program_id": str(program_id),
        "vault_id": str(vault_id),
        "settlement_week": str(settlement_week),
        "lookup_table": str(lookup_table),
        "lookup_table_generation": str(lookup_table_generation),
        "instruction_program_id": str(instruction.program_id),
        "instruction_data_sha256": hashlib.sha256(bytes(instruction.data)).hexdigest(),
        "accounts": [
            {
                "pubkey": str(meta.pubkey),
                "is_signer": meta.is_signer,
                "is_writable": meta.is_writable,
            }
            for meta in instruction.accounts
        ],
    }
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()


def _planned_settlement_size(
    *,
    config: DirectConfig,
    instruction: Instruction,
    lookup_table: AddressLookupTableAccount,
    compute_unit_limit: int,
) -> int:
    instructions = [
        set_compute_unit_limit(compute_unit_limit),
        set_compute_unit_price(_get_priority_fee()),
        instruction,
    ]
    transaction = _build_signed_transaction(
        instructions=instructions,
        fee_payer=config.payer.pubkey(),
        signers=_unique_signers(config.payer, resolve_backend_authority(config)),
        blockhash=Hash.default(),
        address_lookup_table_accounts=[lookup_table],
    )
    return len(bytes(transaction))


async def _lookup_table_seed_slot(
    config: DirectConfig,
    *,
    after_slot: Optional[int] = None,
) -> int:
    async with AsyncClient(config.rpc_url, commitment=Finalized) as client:
        for _ in range(40):
            slot = int((await client.get_slot(commitment=Finalized)).value)
            if after_slot is None or slot > after_slot:
                return slot
            await asyncio.sleep(0.25)
    raise SettlementTransportPending(
        "finalized slot did not advance for lookup-table rotation"
    )


class SettlementTransportManager:
    def __init__(self, *, db: Any, config: DirectConfig) -> None:
        self.db = db
        self.config = config

    async def _get_or_plan(self, vault_id: int) -> LookupTableGeneration:
        slot = await _lookup_table_seed_slot(self.config)
        _, candidate = _make_create_lookup_table_ix(
            authority=self.config.payer.pubkey(),
            payer=self.config.payer.pubkey(),
            recent_slot=slot,
        )
        response = await _rpc(
            self.db,
            "br_get_or_plan_settlement_lookup_table",
            {
                "p_vault_id": str(vault_id),
                "p_program_id": str(self.config.program_id),
                "p_authority": str(self.config.payer.pubkey()),
                "p_recent_slot": str(slot),
                "p_lookup_table_address": str(candidate),
            },
        )
        return LookupTableGeneration.from_row(_first_rpc_row(response))

    async def _rotate(
        self,
        generation: LookupTableGeneration,
    ) -> LookupTableGeneration:
        slot = await _lookup_table_seed_slot(
            self.config,
            after_slot=generation.recent_slot,
        )
        _, candidate = _make_create_lookup_table_ix(
            authority=self.config.payer.pubkey(),
            payer=self.config.payer.pubkey(),
            recent_slot=slot,
        )
        response = await _rpc(
            self.db,
            "br_rotate_settlement_lookup_table",
            {
                "p_current_id": generation.id,
                "p_recent_slot": str(slot),
                "p_lookup_table_address": str(candidate),
            },
        )
        return LookupTableGeneration.from_row(_first_rpc_row(response))

    async def _create_if_missing(
        self,
        generation: LookupTableGeneration,
    ) -> tuple[AddressLookupTable, Optional[str]]:
        state, current_slot = await _fetch_lookup_table_state(
            self.config,
            generation.lookup_table_address,
        )
        if state is not None:
            return state, generation.create_tx_signature
        if generation.status == "active":
            raise SettlementTransportStaleError(
                f"active settlement lookup table {generation.lookup_table_address} is missing"
            )

        instruction, derived = _make_create_lookup_table_ix(
            authority=generation.authority,
            payer=self.config.payer.pubkey(),
            recent_slot=generation.recent_slot,
        )
        if derived != generation.lookup_table_address:
            raise SettlementTransportError("durable lookup-table address derivation changed")
        result = await submit_and_confirm(
            instructions=[instruction],
            signers=[self.config.payer],
            fee_payer=self.config.payer.pubkey(),
            tx_type="settlement_lookup_table_create",
            reference_type="vault",
            reference_id=str(generation.vault_id),
            commitment="finalized",
            rpc_url=self.config.rpc_url,
        )
        if result.failed:
            error = result.error or result.status
            if "recent" in str(error).lower() and current_slot > generation.recent_slot:
                raise SettlementTransportStaleError(
                    "planned settlement lookup-table slot expired before creation"
                )
            raise SettlementTransportPending(
                f"settlement lookup-table creation requires reconciliation: {error}"
            )
        state, _ = await _fetch_lookup_table_state(
            self.config,
            generation.lookup_table_address,
        )
        if state is None:
            raise SettlementTransportPending(
                "finalized settlement lookup-table create is not readable yet"
            )
        return state, result.signature

    async def prepare(
        self,
        *,
        vault_id: int,
        settlement_week: int,
        distribution: SettlementDistributionPlan,
        compute_unit_limit: int,
        on_plan: Optional[TransportPlanCallback] = None,
    ) -> dict[str, Any]:
        required = _settlement_lookup_required_addresses(distribution.instruction)
        if len(required) > LOOKUP_TABLE_MAX_ADDRESSES:
            raise SettlementTransportError(
                "settlement account manifest exceeds lookup-table capacity"
            )
        generation = await self._get_or_plan(vault_id)
        if (
            generation.vault_id != vault_id
            or generation.program_id != str(self.config.program_id)
            or generation.authority != self.config.payer.pubkey()
            or derive_lookup_table_address(
                generation.authority, generation.recent_slot
            )[0]
            != generation.lookup_table_address
        ):
            raise SettlementTransportError(
                "durable settlement lookup-table generation identity is invalid"
            )
        supersession: Optional[dict[str, str]] = None
        for _ in range(2):
            try:
                recipient_manifest = [
                    {
                        "ata": str(ata),
                        "owner": str(owner),
                        "mint": str(mint),
                    }
                    for ata, owner, mint in distribution.recipient_token_accounts
                ]
                instruction_manifest = {
                    "program_id": str(distribution.instruction.program_id),
                    "data_sha256": hashlib.sha256(
                        bytes(distribution.instruction.data)
                    ).hexdigest(),
                    "accounts": [
                        {
                            "pubkey": str(meta.pubkey),
                            "is_signer": bool(meta.is_signer),
                            "is_writable": bool(meta.is_writable),
                        }
                        for meta in distribution.instruction.accounts
                    ],
                }
                plan_payload = {
                    "program_id": str(self.config.program_id),
                    "vault_id": str(vault_id),
                    "settlement_week": str(settlement_week),
                    "payer": str(self.config.payer.pubkey()),
                    "lookup_table_generation_id": generation.id,
                    "lookup_table_address": str(generation.lookup_table_address),
                    "lookup_table_generation": str(generation.generation),
                    "lookup_table_authority": str(generation.authority),
                    "lookup_table_recent_slot": str(generation.recent_slot),
                    "distribution_instruction": instruction_manifest,
                    "required_addresses": [str(value) for value in required],
                    "recipient_token_accounts": recipient_manifest,
                    "expected_manifest_sha256": settlement_transport_manifest_sha256(
                        program_id=self.config.program_id,
                        vault_id=vault_id,
                        settlement_week=settlement_week,
                        lookup_table=generation.lookup_table_address,
                        lookup_table_generation=generation.generation,
                        instruction=distribution.instruction,
                    ),
                }
                if supersession is not None:
                    plan_payload["supersedes"] = supersession
                plan_payload["plan_sha256"] = hashlib.sha256(
                    json.dumps(
                        plan_payload,
                        sort_keys=True,
                        separators=(",", ":"),
                    ).encode("ascii")
                ).hexdigest()
                if on_plan is not None:
                    await on_plan(plan_payload)
                state, create_signature = await self._create_if_missing(generation)
            except SettlementTransportStaleError as exc:
                if on_plan is not None and (
                    "planned settlement lookup-table slot expired before creation"
                    not in str(exc)
                    or supersession is not None
                ):
                    raise SettlementTransportStaleError(
                        "frozen rehearsal transport generation is ambiguous or "
                        "already superseded"
                    ) from exc
                previous = generation
                generation = await self._rotate(generation)
                if (
                    generation.vault_id != vault_id
                    or generation.program_id != str(self.config.program_id)
                    or generation.authority != self.config.payer.pubkey()
                    or generation.generation != previous.generation + 1
                    or derive_lookup_table_address(
                        generation.authority, generation.recent_slot
                    )[0]
                    != generation.lookup_table_address
                ):
                    raise SettlementTransportError(
                        "rotated settlement lookup-table generation identity is invalid"
                    )
                if on_plan is not None:
                    supersession = {
                        "status": "expired",
                        "generation_id": previous.id,
                        "lookup_table_address": str(previous.lookup_table_address),
                        "lookup_table_generation": str(previous.generation),
                        "lookup_table_recent_slot": str(previous.recent_slot),
                        "proof": "finalized create rejection after recent slot",
                    }
                continue
            except SettlementTransportError as exc:
                if "owner mismatch" in str(exc) or "failed to decode" in str(exc):
                    if on_plan is not None:
                        raise SettlementTransportStaleError(
                            "frozen rehearsal transport generation is foreign; "
                            "refusing implicit rotation"
                        ) from exc
                    generation = await self._rotate(generation)
                    continue
                raise

            if state.meta.authority != self.config.payer.pubkey() or (
                state.meta.deactivation_slot != 18_446_744_073_709_551_615
            ):
                if on_plan is not None:
                    raise SettlementTransportStaleError(
                        "frozen rehearsal lookup table authority/state changed"
                    )
                generation = await self._rotate(generation)
                continue
            missing = [key for key in required if key not in set(state.addresses)]
            if len(state.addresses) + len(missing) > LOOKUP_TABLE_MAX_ADDRESSES:
                if on_plan is not None:
                    raise SettlementTransportStaleError(
                        "frozen rehearsal lookup table capacity changed"
                    )
                generation = await self._rotate(generation)
                continue

            recipient_ata_signatures = await _prepare_settlement_recipient_atas(
                rpc_url=self.config.rpc_url,
                payer=self.config.payer,
                vault_id=vault_id,
                instructions=list(distribution.recipient_ata_instructions),
            )

            last_signature: Optional[str] = None
            for offset in range(0, len(missing), LOOKUP_TABLE_EXTEND_CHUNK_SIZE):
                chunk = missing[offset : offset + LOOKUP_TABLE_EXTEND_CHUNK_SIZE]
                result = await submit_and_confirm(
                    instructions=[
                        _make_extend_lookup_table_ix(
                            lookup_table=generation.lookup_table_address,
                            authority=generation.authority,
                            payer=self.config.payer.pubkey(),
                            addresses=chunk,
                        )
                    ],
                    signers=[self.config.payer],
                    fee_payer=self.config.payer.pubkey(),
                    tx_type="settlement_lookup_table_extend",
                    reference_type="vault",
                    reference_id=str(vault_id),
                    commitment="finalized",
                    rpc_url=self.config.rpc_url,
                )
                if result.failed:
                    raise SettlementTransportPending(
                        "settlement lookup-table extension requires reconciliation: "
                        f"{result.error or result.status}"
                    )
                last_signature = result.signature

            state, current_slot = await _fetch_lookup_table_state(
                self.config,
                generation.lookup_table_address,
            )
            if state is None:
                raise SettlementTransportPending("settlement lookup table disappeared")
            try:
                lookup_account = _validate_settlement_lookup_table_state(
                    address=generation.lookup_table_address,
                    state=state,
                    current_slot=current_slot,
                    expected_authority=self.config.payer.pubkey(),
                    required_addresses=required,
                )
            except ValueError as exc:
                raise SettlementTransportPending(
                    "finalized settlement lookup-table state has not caught up: "
                    f"{exc}"
                ) from exc
            manifest = settlement_transport_manifest_sha256(
                program_id=self.config.program_id,
                vault_id=vault_id,
                settlement_week=settlement_week,
                lookup_table=generation.lookup_table_address,
                lookup_table_generation=generation.generation,
                instruction=distribution.instruction,
            )
            planned_bytes = _planned_settlement_size(
                config=self.config,
                instruction=distribution.instruction,
                lookup_table=lookup_account,
                compute_unit_limit=compute_unit_limit,
            )
            if planned_bytes > SETTLEMENT_V0_REVIEW_LIMIT_BYTES:
                raise SettlementTransportError(
                    f"v0 settlement is {planned_bytes} bytes; reviewed limit is "
                    f"{SETTLEMENT_V0_REVIEW_LIMIT_BYTES}"
                )
            await _rpc(
                self.db,
                "br_record_settlement_lookup_table_ready",
                {
                    "p_generation_id": generation.id,
                    "p_create_tx_signature": create_signature,
                    "p_last_tx_signature": last_signature,
                    "p_last_extended_slot": str(state.meta.last_extended_slot),
                    "p_address_count": len(state.addresses),
                    "p_manifest_sha256": manifest,
                },
            )
            return {
                "transaction_version": "0",
                "lookup_table_address": str(generation.lookup_table_address),
                "lookup_table_generation": str(generation.generation),
                "manifest_sha256": manifest,
                "last_extended_slot": str(state.meta.last_extended_slot),
                "lookup_table_address_count": str(len(state.addresses)),
                "required_account_count": str(len(required)),
                "planned_serialized_bytes": str(planned_bytes),
                "packet_limit_bytes": str(PACKET_DATA_SIZE),
                "review_limit_bytes": str(SETTLEMENT_V0_REVIEW_LIMIT_BYTES),
                "leaderboard_recipient_count": str(
                    distribution.leaderboard_recipient_count
                ),
                "local_legend_recipient_count": str(
                    distribution.local_legend_recipient_count
                ),
                "stake_inventory_count": str(distribution.stake_inventory_count),
                "recipient_ata_signatures": recipient_ata_signatures,
            }

        raise SettlementTransportError(
            "settlement lookup-table rotation did not produce a usable generation"
        )


async def validate_frozen_settlement_transport(
    *,
    config: DirectConfig,
    vault_id: int,
    settlement_week: int,
    instruction: Instruction,
    transport_plan: Optional[Mapping[str, Any]],
    compute_unit_limit: int,
) -> AddressLookupTableAccount:
    if not isinstance(transport_plan, Mapping):
        raise SettlementTransportStaleError("frozen settlement transport is missing")
    try:
        version = _exact_nonnegative_int(
            transport_plan["transaction_version"],
            "transaction_version",
        )
        address = Pubkey.from_string(str(transport_plan["lookup_table_address"]))
        generation = _exact_nonnegative_int(
            transport_plan["lookup_table_generation"],
            "lookup_table_generation",
        )
        expected_manifest = str(transport_plan["manifest_sha256"])
        expected_last_extended_slot = _exact_nonnegative_int(
            transport_plan["last_extended_slot"],
            "last_extended_slot",
        )
        expected_bytes = _exact_nonnegative_int(
            transport_plan["planned_serialized_bytes"],
            "planned_serialized_bytes",
        )
    except (KeyError, ValueError) as exc:
        raise SettlementTransportStaleError(
            "frozen settlement transport is malformed"
        ) from exc
    if version != SETTLEMENT_TRANSPORT_VERSION:
        raise SettlementTransportStaleError("unsupported settlement transaction version")

    try:
        state, current_slot = await _fetch_lookup_table_state(config, address)
    except SettlementTransportError as exc:
        raise SettlementTransportStaleError(str(exc)) from exc
    if state is None:
        raise SettlementTransportStaleError(f"settlement lookup table {address} is missing")
    if state.meta.last_extended_slot != expected_last_extended_slot:
        raise SettlementTransportStaleError(
            "settlement lookup-table extension slot changed after preparation"
        )
    try:
        lookup_account = _validate_settlement_lookup_table_state(
            address=address,
            state=state,
            current_slot=current_slot,
            expected_authority=config.payer.pubkey(),
            required_addresses=_settlement_lookup_required_addresses(instruction),
        )
    except ValueError as exc:
        raise SettlementTransportStaleError(str(exc)) from exc
    manifest = settlement_transport_manifest_sha256(
        program_id=config.program_id,
        vault_id=vault_id,
        settlement_week=settlement_week,
        lookup_table=address,
        lookup_table_generation=generation,
        instruction=instruction,
    )
    if manifest != expected_manifest:
        raise SettlementTransportStaleError(
            "settlement account manifest changed after preparation"
        )
    try:
        actual_bytes = _planned_settlement_size(
            config=config,
            instruction=instruction,
            lookup_table=lookup_account,
            compute_unit_limit=compute_unit_limit,
        )
    except ValueError as exc:
        raise SettlementTransportStaleError(str(exc)) from exc
    if actual_bytes != expected_bytes or actual_bytes > SETTLEMENT_V0_REVIEW_LIMIT_BYTES:
        raise SettlementTransportStaleError(
            "settlement serialized size changed after preparation"
        )
    return lookup_account
