"""Finalized Solana reads and exact settlement materialization snapshots."""

from __future__ import annotations

import hashlib
import json
import struct
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Mapping, Optional, Union

from solana.rpc.async_api import AsyncClient
from solana.rpc.commitment import Finalized
from solders.pubkey import Pubkey

from ..solana_direct import (
    DirectConfig,
    _account_data_bytes,
    _decode_anchor_vault_account,
    _derive_local_legend_pda,
    _derive_vault_counter_pda,
    _derive_vault_pda,
    parse_local_legend,
    parse_vault_counter,
)
from .settlement_queue import SettlementClaim, parse_u64, u64_string, uint39_string


MAX_GET_MULTIPLE_VAULTS_PER_BATCH = 99
VaultReader = Callable[
    [int], Awaitable[Union[dict[str, Any], "VaultAbsenceEvidence", None]]
]
SignatureReader = Callable[[str], Awaitable[tuple[str, Optional[str]]]]
LegendReader = Callable[[int], Awaitable[Optional["LocalLegendChainEvidence"]]]

CURRENT_AMOUNT_FIELDS = (
    "pending_rewards",
    "cal_tribute_accumulated",
    "carry_record_royalty",
    "carry_stakers",
    "carry_local_legend",
    "carry_pol",
    "carry_treasury",
)
NEXT_AMOUNT_FIELDS = (
    "pending_rewards_next_week",
    "cal_tribute_accumulated_next",
)
SNAPSHOT_U64_FIELDS = (
    "id",
    "open_settlement_week",
    *CURRENT_AMOUNT_FIELDS,
    *NEXT_AMOUNT_FIELDS,
)


class SettlementChainError(RuntimeError):
    """An authoritative settlement chain read failed."""


class IncompleteVaultScopeError(SettlementChainError):
    """VaultCounter scope could not be materialized completely."""


@dataclass(frozen=True)
class ScopeBatchEvidence:
    start_vault_id: int
    end_vault_id_exclusive: int
    source_slot: int
    account_hash: str

    def as_json(self) -> dict[str, str]:
        return {
            "start_vault_id": str(self.start_vault_id),
            "end_vault_id_exclusive": str(self.end_vault_id_exclusive),
            "source_slot": str(self.source_slot),
            "account_hash": self.account_hash,
        }


@dataclass(frozen=True)
class ScopeSnapshotRead:
    counter_count_before: int
    counter_count_after: int
    source_slot_min: int
    source_slot_max: int
    vaults: tuple[dict[str, Any], ...]
    batch_evidence: tuple[ScopeBatchEvidence, ...] = ()


SnapshotReader = Callable[
    [],
    Awaitable[
        Union[
            ScopeSnapshotRead,
            tuple[int, int, int, tuple[dict[str, Any], ...]],
        ]
    ],
]


@dataclass(frozen=True)
class AuthoritativeVaultScope:
    counter_count: int
    source_slot: int
    vaults: tuple[dict[str, Any], ...]
    source_slot_min: Optional[int] = None
    source_slot_max: Optional[int] = None
    batch_evidence: tuple[ScopeBatchEvidence, ...] = ()

    def bootstrap_evidence(self) -> list[dict[str, str]]:
        evidence: list[dict[str, str]] = []
        for vault in self.vaults:
            exact_snapshot = _exact_snapshot(vault)
            snapshot_json = json.dumps(
                exact_snapshot,
                sort_keys=True,
                separators=(",", ":"),
            )
            evidence.append({
                "vault_id": u64_string(vault.get("id"), field_name="vault_id"),
                "vault_pda": str(vault.get("pda") or ""),
                "vault_signature": str(vault.get("signature_hex") or ""),
                "open_settlement_week": u64_string(
                    vault.get("open_settlement_week"),
                    field_name="open_settlement_week",
                ),
                "snapshot_hash": hashlib.sha256(snapshot_json.encode("utf-8")).hexdigest(),
            })
        return evidence

    def scope_evidence(self) -> dict[str, Any]:
        slot_min = self.source_slot_min if self.source_slot_min is not None else self.source_slot
        slot_max = self.source_slot_max if self.source_slot_max is not None else self.source_slot
        return {
            "commitment": "finalized",
            "counter_count": str(self.counter_count),
            "source_slot_min": str(slot_min),
            "source_slot_max": str(slot_max),
            "batches": [batch.as_json() for batch in self.batch_evidence],
        }


@dataclass(frozen=True)
class VaultAbsenceEvidence:
    """A null Vault and its validated counter from one finalized response."""

    counter_count: int
    source_slot: int
    chain_commitment: str = "finalized"


@dataclass(frozen=True)
class ChainReconciliationEvidence:
    open_settlement_week: Optional[int]
    signature_state: str
    signature_error: Optional[str]
    chain_commitment: str = "finalized"
    source_slot: Optional[int] = None
    absent_vault_counter_count: Optional[int] = None


@dataclass(frozen=True)
class LocalLegendChainEvidence:
    holder: str
    is_active: bool
    term_start_epoch: int
    term_end_epoch: int


def partition_vault_scope(counter_count: int) -> list[tuple[int, int]]:
    """Partition the complete counter scope while reserving one RPC slot for the counter."""
    count = parse_u64(counter_count, field_name="VaultCounter.count")
    return [
        (start, min(start + MAX_GET_MULTIPLE_VAULTS_PER_BATCH, count))
        for start in range(0, count, MAX_GET_MULTIPLE_VAULTS_PER_BATCH)
    ]


def _amount(snapshot: Mapping[str, Any], field_name: str) -> int:
    return parse_u64(snapshot.get(field_name, 0) or 0, field_name=field_name)


def _exact_snapshot(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    exact = {
        field_name: u64_string(snapshot.get(field_name, 0) or 0, field_name=field_name)
        for field_name in SNAPSHOT_U64_FIELDS
    }
    exact["signature_hex"] = str(snapshot.get("signature_hex") or "")
    exact["pda"] = str(snapshot.get("pda") or "")
    exact["account_layout"] = str(snapshot.get("account_layout") or "unknown")
    return exact


def build_materialization_job(
    snapshot: Mapping[str, Any],
    *,
    settlement_week: int,
) -> dict[str, Any]:
    """Build one exact job/no-op record for a counter-indexed vault."""
    target_week = parse_u64(settlement_week, field_name="settlement_week")
    vault_id = parse_u64(snapshot.get("id"), field_name="vault_id")
    open_week = parse_u64(
        snapshot.get("open_settlement_week"),
        field_name="open_settlement_week",
    )
    signature = str(snapshot.get("signature_hex") or "")
    if not signature:
        raise IncompleteVaultScopeError(f"vault {vault_id} has no authoritative signature")

    current_amounts = {field: _amount(snapshot, field) for field in CURRENT_AMOUNT_FIELDS}
    next_amounts = {field: _amount(snapshot, field) for field in NEXT_AMOUNT_FIELDS}
    current_value = sum(current_amounts.values())
    next_value = sum(next_amounts.values())

    state: str
    skip_reason: Optional[str] = None
    blocked_reason: Optional[str] = None
    auto_roll = False
    selected_cal = 0
    selected_dung = 0

    if open_week == target_week:
        # Zero-value settlement still promotes the frozen stake snapshots.
        state = "ready"
        selected_cal = current_amounts["cal_tribute_accumulated"]
        selected_dung = current_amounts["pending_rewards"]
    elif open_week > target_week:
        state = "reconciling"
    else:
        state = "blocked"
        blocked_reason = (
            f"vault open week {open_week} cannot safely reach planned week {target_week}; "
            "the stored open week must settle first, including at zero"
        )

    return {
        "vault_id": u64_string(vault_id, field_name="vault_id"),
        "vault_signature": signature,
        "state": state,
        "skip_reason": skip_reason,
        "blocked_reason": blocked_reason,
        "expected_pre_open_week": u64_string(
            open_week,
            field_name="expected_pre_open_week",
        ),
        "auto_roll_from_empty": auto_roll,
        "cal_to_convert": u64_string(selected_cal, field_name="cal_to_convert"),
        "dung_to_mint": u64_string(selected_dung, field_name="dung_to_mint"),
        "current_week_value": uint39_string(
            current_value,
            field_name="current_week_value",
        ),
        "next_week_value": uint39_string(next_value, field_name="next_week_value"),
        "pending_rewards": u64_string(
            current_amounts["pending_rewards"],
            field_name="pending_rewards",
        ),
        "cal_tribute_accumulated": u64_string(
            current_amounts["cal_tribute_accumulated"],
            field_name="cal_tribute_accumulated",
        ),
        "pending_rewards_next_week": u64_string(
            next_amounts["pending_rewards_next_week"],
            field_name="pending_rewards_next_week",
        ),
        "cal_tribute_accumulated_next": u64_string(
            next_amounts["cal_tribute_accumulated_next"],
            field_name="cal_tribute_accumulated_next",
        ),
        "carry_record_royalty": u64_string(
            current_amounts["carry_record_royalty"],
            field_name="carry_record_royalty",
        ),
        "carry_stakers": u64_string(
            current_amounts["carry_stakers"],
            field_name="carry_stakers",
        ),
        "carry_local_legend": u64_string(
            current_amounts["carry_local_legend"],
            field_name="carry_local_legend",
        ),
        "carry_pol": u64_string(current_amounts["carry_pol"], field_name="carry_pol"),
        "carry_treasury": u64_string(
            current_amounts["carry_treasury"],
            field_name="carry_treasury",
        ),
        "raw_snapshot": _exact_snapshot(snapshot),
    }


class SettlementChain:
    """Reads the complete finalized VaultCounter scope directly from Solana."""

    def __init__(
        self,
        config: DirectConfig,
        *,
        snapshot_reader: Optional[SnapshotReader] = None,
        vault_reader: Optional[VaultReader] = None,
        signature_reader: Optional[SignatureReader] = None,
        legend_reader: Optional[LegendReader] = None,
        scope_read_retries: int = 3,
    ) -> None:
        self.config = config
        self._snapshot_reader = snapshot_reader or self._read_rpc_snapshot
        self._vault_reader = vault_reader or self._read_finalized_vault
        self._signature_reader = signature_reader or self._read_signature
        self._legend_reader = legend_reader or self._read_local_legend
        self.scope_read_retries = max(int(scope_read_retries), 1)

    async def read_chain_time(self) -> int:
        """Use the finalized Clock sysvar, never the worker's wall clock."""
        async with AsyncClient(self.config.rpc_url, commitment=Finalized) as client:
            response = await client.get_account_info(
                Pubkey.from_string("SysvarC1ock11111111111111111111111111111111"),
                commitment=Finalized,
            )
        if response.value is None:
            raise SettlementChainError("finalized Clock sysvar is unavailable")
        data = _account_data_bytes(response.value.data)
        if len(data) != 40:
            raise SettlementChainError("finalized Clock sysvar has an invalid layout")
        return struct.unpack_from("<q", data, 32)[0]

    @staticmethod
    def _account_discriminator(name: str) -> bytes:
        return hashlib.sha256(f"account:{name}".encode("utf-8")).digest()[:8]

    def _validate_program_account(
        self,
        account: Any,
        *,
        account_name: str,
        pda: Any,
    ) -> bytes:
        if account is None:
            raise IncompleteVaultScopeError(
                f"authoritative {account_name} account is missing"
            )
        if str(getattr(account, "owner", "")) != str(self.config.program_id):
            raise IncompleteVaultScopeError(
                f"authoritative {account_name} {pda} has the wrong program owner"
            )
        data = _account_data_bytes(account.data)
        expected = self._account_discriminator(account_name)
        if len(data) < len(expected) or data[:8] != expected:
            raise IncompleteVaultScopeError(
                f"authoritative {account_name} {pda} has the wrong discriminator"
            )
        return data

    def _decode_counter(self, account: Any, counter_pda: Any) -> tuple[int, int, bytes]:
        data = self._validate_program_account(
            account,
            account_name="VaultCounter",
            pda=counter_pda,
        )
        counter = parse_vault_counter(data)
        if counter is None:
            raise IncompleteVaultScopeError("VaultCounter account is malformed")
        _, expected_bump = _derive_vault_counter_pda(self.config.program_id)
        if counter.bump != expected_bump:
            raise IncompleteVaultScopeError("VaultCounter PDA bump is invalid")
        return (
            parse_u64(counter.count, field_name="VaultCounter.count"),
            counter.bump,
            data,
        )

    async def _read_rpc_snapshot(self) -> ScopeSnapshotRead:
        counter_pda, _ = _derive_vault_counter_pda(self.config.program_id)
        vaults: list[dict[str, Any]] = []
        batch_evidence: list[ScopeBatchEvidence] = []
        observed_slots: list[int] = []

        async with AsyncClient(self.config.rpc_url, commitment=Finalized) as client:
            preliminary_response = await client.get_account_info(
                counter_pda,
                commitment=Finalized,
            )
            preliminary_count, _, _ = self._decode_counter(
                preliminary_response.value,
                counter_pda,
            )
            preliminary_slot = parse_u64(
                int(getattr(getattr(preliminary_response, "context", None), "slot", 0) or 0),
                field_name="VaultCounter.preliminary_slot",
            )
            observed_slots.append(preliminary_slot)

            for start, end in partition_vault_scope(preliminary_count):
                vault_pdas = [
                    _derive_vault_pda(vault_id, self.config.program_id)[0]
                    for vault_id in range(start, end)
                ]
                response = await client.get_multiple_accounts(
                    [counter_pda, *vault_pdas],
                    commitment=Finalized,
                )
                accounts = tuple(response.value or ())
                if len(accounts) != len(vault_pdas) + 1:
                    raise IncompleteVaultScopeError(
                        f"finalized scope batch {start}:{end} is incomplete"
                    )
                batch_count, _, counter_data = self._decode_counter(accounts[0], counter_pda)
                batch_slot = parse_u64(
                    int(getattr(getattr(response, "context", None), "slot", 0) or 0),
                    field_name="VaultCounter.batch_slot",
                )
                observed_slots.append(batch_slot)
                if batch_count != preliminary_count:
                    return ScopeSnapshotRead(
                        counter_count_before=preliminary_count,
                        counter_count_after=batch_count,
                        source_slot_min=min(observed_slots),
                        source_slot_max=max(observed_slots),
                        vaults=(),
                        batch_evidence=tuple(batch_evidence),
                    )

                hash_input = bytearray(counter_data)
                for vault_id, (vault_pda, account) in enumerate(
                    zip(vault_pdas, accounts[1:]),
                    start=start,
                ):
                    data = self._validate_program_account(
                        account,
                        account_name="Vault",
                        pda=vault_pda,
                    )
                    hash_input.extend(data)
                    try:
                        decoded = _decode_anchor_vault_account(data, vault_pda)
                    except Exception as exc:
                        raise IncompleteVaultScopeError(
                            f"authoritative vault {vault_id} could not be decoded: {exc}"
                        ) from exc
                    decoded_id = parse_u64(
                        decoded.get("id"),
                        field_name=f"vault {vault_id} id",
                    )
                    expected_pda, _ = _derive_vault_pda(decoded_id, self.config.program_id)
                    if decoded_id != vault_id or expected_pda != vault_pda:
                        raise IncompleteVaultScopeError(
                            f"authoritative vault {vault_id} has invalid PDA or decoded id {decoded_id}"
                        )
                    decoded["_commitment"] = "finalized"
                    decoded["_source_slot"] = batch_slot
                    vaults.append(decoded)

                batch_evidence.append(ScopeBatchEvidence(
                    start_vault_id=start,
                    end_vault_id_exclusive=end,
                    source_slot=batch_slot,
                    account_hash=hashlib.sha256(bytes(hash_input)).hexdigest(),
                ))

            final_response = await client.get_account_info(
                counter_pda,
                commitment=Finalized,
            )
            final_count, _, _ = self._decode_counter(final_response.value, counter_pda)
            final_slot = parse_u64(
                int(getattr(getattr(final_response, "context", None), "slot", 0) or 0),
                field_name="VaultCounter.final_slot",
            )
            observed_slots.append(final_slot)

        return ScopeSnapshotRead(
            counter_count_before=preliminary_count,
            counter_count_after=final_count,
            source_slot_min=min(observed_slots),
            source_slot_max=max(observed_slots),
            vaults=tuple(vaults),
            batch_evidence=tuple(batch_evidence),
        )

    async def _read_finalized_vault(
        self, vault_id: int,
    ) -> Union[dict[str, Any], VaultAbsenceEvidence]:
        vault_pda, _ = _derive_vault_pda(vault_id, self.config.program_id)
        counter_pda, _ = _derive_vault_counter_pda(self.config.program_id)
        async with AsyncClient(self.config.rpc_url, commitment=Finalized) as client:
            response = await client.get_multiple_accounts(
                [counter_pda, vault_pda], commitment=Finalized,
            )
        accounts = tuple(response.value or ())
        if len(accounts) != 2:
            raise SettlementChainError("finalized vault/counter response is incomplete")
        source_slot = parse_u64(
            getattr(getattr(response, "context", None), "slot", None),
            field_name="vault.source_slot",
        )
        if accounts[1] is None:
            # This is only an absence candidate: reconciliation must also prove
            # this finalized bank is newer than the run's materialization slot.
            counter_count, _, _ = self._decode_counter(accounts[0], counter_pda)
            if source_slot == 0 or vault_id < counter_count:
                raise SettlementChainError(
                    f"vault {vault_id} absence is not proven outside finalized counter scope"
                )
            return VaultAbsenceEvidence(counter_count, source_slot)
        data = self._validate_program_account(
            accounts[1],
            account_name="Vault",
            pda=vault_pda,
        )
        decoded = _decode_anchor_vault_account(data, vault_pda)
        decoded_id = parse_u64(decoded.get("id"), field_name="vault_id")
        if decoded_id != vault_id:
            raise SettlementChainError(
                f"vault {vault_id} finalized read decoded vault {decoded_id}"
            )
        decoded["_commitment"] = "finalized"
        decoded["_source_slot"] = source_slot
        return decoded

    async def _read_local_legend(
        self,
        vault_id: int,
    ) -> Optional[LocalLegendChainEvidence]:
        legend_pda, _ = _derive_local_legend_pda(vault_id, self.config.program_id)
        async with AsyncClient(self.config.rpc_url, commitment=Finalized) as client:
            response = await client.get_account_info(legend_pda, commitment=Finalized)
        if response.value is None:
            return None
        data = self._validate_program_account(
            response.value,
            account_name="LocalLegend",
            pda=legend_pda,
        )
        parsed = parse_local_legend(data)
        if parsed is None:
            raise SettlementChainError(
                f"LocalLegend account for vault {vault_id} is malformed"
            )
        return LocalLegendChainEvidence(
            holder=str(parsed.holder),
            is_active=parsed.is_active,
            term_start_epoch=parse_u64(
                parsed.term_start_epoch,
                field_name="LocalLegend.term_start_epoch",
            ),
            term_end_epoch=parse_u64(
                parsed.term_end_epoch,
                field_name="LocalLegend.term_end_epoch",
            ),
        )

    async def _read_signature(self, signature: str) -> tuple[str, Optional[str]]:
        if not signature:
            return "absent", None
        try:
            from solders.signature import Signature

            parsed_signature = Signature.from_string(signature)
            async with AsyncClient(self.config.rpc_url, commitment=Finalized) as client:
                response = await client.get_signature_statuses(
                    [parsed_signature],
                    search_transaction_history=True,
                )
        except Exception as exc:
            return "unknown", str(exc)

        status = response.value[0] if response.value else None
        if status is None:
            return "absent", None
        if getattr(status, "err", None) is not None:
            return "failed", str(status.err)
        confirmation = str(getattr(status, "confirmation_status", "") or "").lower()
        if "finalized" in confirmation:
            return "finalized", None
        if "confirmed" in confirmation:
            return "confirmed", None
        return "pending", None

    @staticmethod
    def _normalize_snapshot_read(
        result: Union[
            ScopeSnapshotRead,
            tuple[int, int, int, tuple[dict[str, Any], ...]],
        ],
    ) -> ScopeSnapshotRead:
        if isinstance(result, ScopeSnapshotRead):
            return result
        before, after, slot, vaults = result
        return ScopeSnapshotRead(
            counter_count_before=before,
            counter_count_after=after,
            source_slot_min=slot,
            source_slot_max=slot,
            vaults=vaults,
        )

    async def read_authoritative_scope(self) -> AuthoritativeVaultScope:
        for attempt in range(self.scope_read_retries):
            try:
                read = self._normalize_snapshot_read(await self._snapshot_reader())
                before_count = parse_u64(
                    read.counter_count_before,
                    field_name="preliminary VaultCounter.count",
                )
                after_count = parse_u64(
                    read.counter_count_after,
                    field_name="final VaultCounter.count",
                )
                slot_min = parse_u64(read.source_slot_min, field_name="scope.source_slot_min")
                slot_max = parse_u64(read.source_slot_max, field_name="scope.source_slot_max")
            except SettlementChainError:
                raise
            except Exception as exc:
                raise SettlementChainError(f"authoritative scope read failed: {exc}") from exc

            if before_count != after_count:
                if attempt + 1 < self.scope_read_retries:
                    continue
                raise IncompleteVaultScopeError(
                    "VaultCounter changed during authoritative read; retry budget exhausted"
                )
            if slot_min > slot_max:
                raise IncompleteVaultScopeError("authoritative scope slot range is invalid")

            vaults = tuple(dict(vault) for vault in read.vaults)
            if len(vaults) != after_count:
                raise IncompleteVaultScopeError(
                    f"VaultCounter requires {after_count} vaults, read {len(vaults)}"
                )
            seen_ids: set[int] = set()
            for expected_id, vault in enumerate(vaults):
                parsed_id = parse_u64(
                    vault.get("id"),
                    field_name=f"vault {expected_id} id",
                )
                if parsed_id != expected_id or parsed_id in seen_ids:
                    raise IncompleteVaultScopeError(
                        f"authoritative vault {expected_id} decoded as vault {parsed_id}"
                    )
                seen_ids.add(parsed_id)

            return AuthoritativeVaultScope(
                counter_count=after_count,
                source_slot=slot_max,
                source_slot_min=slot_min,
                source_slot_max=slot_max,
                vaults=vaults,
                batch_evidence=read.batch_evidence,
            )

        raise IncompleteVaultScopeError("authoritative scope retry budget exhausted")

    async def read_local_legend(
        self,
        vault_id: int,
    ) -> Optional[LocalLegendChainEvidence]:
        try:
            return await self._legend_reader(vault_id)
        except SettlementChainError:
            raise
        except Exception as exc:
            raise SettlementChainError(
                f"LocalLegend read failed for vault {vault_id}: {exc}"
            ) from exc

    async def read_reconciliation_evidence(
        self,
        claim: SettlementClaim,
        *,
        signature: Optional[str] = None,
    ) -> ChainReconciliationEvidence:
        vault = await self._vault_reader(claim.vault_id)
        if isinstance(vault, VaultAbsenceEvidence):
            return ChainReconciliationEvidence(
                open_settlement_week=None,
                signature_state="unknown",
                signature_error=None,
                chain_commitment=vault.chain_commitment,
                source_slot=vault.source_slot,
                absent_vault_counter_count=vault.counter_count,
            )
        if vault is None:
            raise SettlementChainError(
                f"vault {claim.vault_id} absence lacks finalized counter evidence"
            )
        decoded_id = parse_u64(vault.get("id"), field_name="vault_id")
        if decoded_id != claim.vault_id:
            raise SettlementChainError(
                f"vault {claim.vault_id} reconciliation decoded vault {decoded_id}"
            )
        signature_state, signature_error = await self._signature_reader(
            signature or claim.tx_signature or ""
        )
        return ChainReconciliationEvidence(
            open_settlement_week=parse_u64(
                vault.get("open_settlement_week"),
                field_name="open_settlement_week",
            ),
            signature_state=signature_state,
            signature_error=signature_error,
            chain_commitment=str(vault.get("_commitment") or "finalized"),
            source_slot=(
                parse_u64(vault.get("_source_slot"), field_name="vault.source_slot")
                if vault.get("_source_slot") is not None
                else None
            ),
        )
