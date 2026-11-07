"""Durable database boundary for settlement planning and execution."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, Iterable, Mapping, Optional

if TYPE_CHECKING:
    from .settlement_chain import AuthoritativeVaultScope


U64_MAX = 18_446_744_073_709_551_615
NUMERIC_39_MAX = (10**39) - 1
DEFAULT_LEASE_SECONDS = 300


class SettlementStateError(RuntimeError):
    """Base error for durable settlement state failures."""


class SettlementStateReadError(SettlementStateError):
    """The planning cursor could not be read authoritatively."""


class SettlementBootstrapRequired(SettlementStateError):
    """The durable planning row exists but has no authoritative bootstrap yet."""


class SettlementLeaseLost(SettlementStateError):
    """A fenced transition was rejected because the lease is no longer owned."""


def parse_u64(value: Any, *, field_name: str = "value") -> int:
    """Parse an exact u64 without accepting floats or lossy numeric syntax."""
    if isinstance(value, bool) or isinstance(value, float):
        raise ValueError(f"{field_name} must be an exact u64")
    if isinstance(value, int):
        parsed = value
    elif isinstance(value, Decimal):
        if value != value.to_integral_value():
            raise ValueError(f"{field_name} must be an exact u64")
        parsed = int(value)
    elif isinstance(value, str):
        normalized = value.strip()
        if not normalized or not normalized.isascii() or not normalized.isdigit():
            raise ValueError(f"{field_name} must be an exact u64 decimal string")
        if len(normalized) > 1 and normalized.startswith("0"):
            raise ValueError(f"{field_name} must use canonical u64 decimal form")
        try:
            decimal_value = Decimal(normalized)
        except InvalidOperation as exc:
            raise ValueError(f"{field_name} must be an exact u64") from exc
        parsed = int(decimal_value)
    else:
        raise ValueError(f"{field_name} must be an exact u64")

    if parsed < 0 or parsed > U64_MAX:
        raise ValueError(f"{field_name} is outside the u64 range")
    return parsed


def u64_string(value: Any, *, field_name: str = "value") -> str:
    """Serialize a protocol quantity for JSON/PostgREST without float coercion."""
    return str(parse_u64(value, field_name=field_name))


def uint39_string(value: Any, *, field_name: str = "value") -> str:
    """Serialize a nonnegative derived aggregate that fits NUMERIC(39,0)."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"{field_name} must be an exact nonnegative integer")
    if value < 0 or value > NUMERIC_39_MAX:
        raise ValueError(f"{field_name} is outside the NUMERIC(39,0) range")
    return str(value)


def safe_bootstrap_cursor(
    open_weeks: Iterable[Any],
    *,
    latest_finalizable_week: Any,
) -> int:
    """Derive the last-safe cursor without skipping any possibly open week."""
    latest = parse_u64(
        latest_finalizable_week,
        field_name="latest_finalizable_week",
    )
    parsed_open_weeks = [
        parse_u64(value, field_name="open_settlement_week")
        for value in open_weeks
    ]
    if not parsed_open_weeks:
        return latest
    return min(latest, min(parsed_open_weeks) - 1)


def _parse_planning_cursor(value: Any) -> int:
    if value in (-1, "-1", Decimal(-1)):
        return -1
    return parse_u64(value, field_name="last_materialized_week")


def _response_data(response: Any) -> Any:
    return getattr(response, "data", None)


def _first_row(data: Any) -> Optional[dict[str, Any]]:
    if isinstance(data, list):
        if not data:
            return None
        row = data[0]
    else:
        row = data
    return dict(row) if isinstance(row, Mapping) else None


def _rpc_count(data: Any) -> int:
    if isinstance(data, list):
        data = data[0] if data else 0
    if isinstance(data, Mapping):
        data = next(iter(data.values()), 0)
    return int(data or 0)


@dataclass(frozen=True)
class SettlementClaim:
    id: str
    run_id: str
    settlement_week: int
    vault_id: int
    vault_signature: str
    state: str
    lease_owner: str
    lease_token: str
    attempt_count: int
    expected_pre_open_week: int
    auto_roll_from_empty: bool
    dung_to_mint: int
    prepared_tx_signature: Optional[str]
    tx_signature: Optional[str]
    last_error_class: Optional[str]
    last_error: Optional[str]
    legacy_distribution_id: Optional[str]
    submit_started_at: Optional[str]
    precondition_intent: Optional[dict[str, Any]]
    precondition_result: Optional[dict[str, Any]]
    raw_snapshot: dict[str, Any]

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SettlementClaim":
        lease_token = row.get("lease_token")
        lease_owner = row.get("lease_owner")
        if not lease_token or not lease_owner:
            raise SettlementStateError("claimed settlement job is missing its lease fence")
        return cls(
            id=str(row["id"]),
            run_id=str(row["run_id"]),
            settlement_week=parse_u64(row["settlement_week"], field_name="settlement_week"),
            vault_id=parse_u64(row["vault_id"], field_name="vault_id"),
            vault_signature=str(row["vault_signature"]),
            state=str(row["state"]),
            lease_owner=str(lease_owner),
            lease_token=str(lease_token),
            attempt_count=int(row.get("attempt_count") or 0),
            expected_pre_open_week=parse_u64(
                row["expected_pre_open_week"],
                field_name="expected_pre_open_week",
            ),
            auto_roll_from_empty=bool(row.get("auto_roll_from_empty")),
            dung_to_mint=parse_u64(
                row.get("dung_to_mint", 0),
                field_name="dung_to_mint",
            ),
            prepared_tx_signature=(
                str(row["prepared_tx_signature"])
                if row.get("prepared_tx_signature")
                else None
            ),
            tx_signature=str(row["tx_signature"]) if row.get("tx_signature") else None,
            last_error_class=(
                str(row["last_error_class"]) if row.get("last_error_class") else None
            ),
            last_error=str(row["last_error"]) if row.get("last_error") else None,
            legacy_distribution_id=(
                str(row["legacy_distribution_id"])
                if row.get("legacy_distribution_id")
                else None
            ),
            submit_started_at=(
                str(row["submit_started_at"]) if row.get("submit_started_at") else None
            ),
            precondition_intent=(
                dict(row["precondition_intent"])
                if isinstance(row.get("precondition_intent"), Mapping)
                else None
            ),
            precondition_result=(
                dict(row["precondition_result"])
                if isinstance(row.get("precondition_result"), Mapping)
                else None
            ),
            raw_snapshot=dict(row.get("raw_snapshot") or {}),
        )


@dataclass(frozen=True)
class SettlementNotificationEvent:
    id: str
    job_id: str
    vault_id: int
    vault_signature: str
    settlement_week: int
    raw_pending_dung: int
    total_distributed: Optional[int]
    tx_signature: str
    lease_owner: str
    lease_token: str

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "SettlementNotificationEvent":
        if not row.get("lease_owner") or not row.get("lease_token"):
            raise SettlementStateError("claimed notification is missing its lease fence")
        total = row.get("total_distributed")
        return cls(
            id=str(row["id"]),
            job_id=str(row["job_id"]),
            vault_id=parse_u64(row["vault_id"], field_name="vault_id"),
            vault_signature=str(row["vault_signature"]),
            settlement_week=parse_u64(
                row["settlement_week"],
                field_name="settlement_week",
            ),
            raw_pending_dung=parse_u64(
                row["raw_pending_dung"],
                field_name="raw_pending_dung",
            ),
            total_distributed=(
                parse_u64(total, field_name="total_distributed")
                if total is not None
                else None
            ),
            tx_signature=str(row["tx_signature"]),
            lease_owner=str(row["lease_owner"]),
            lease_token=str(row["lease_token"]),
        )

    def as_notification_metadata(self) -> dict[str, str]:
        metadata = {
            "vault_id": str(self.vault_id),
            "settlement_week": str(self.settlement_week),
            "raw_pending_dung": str(self.raw_pending_dung),
            "tx_signature": self.tx_signature,
        }
        if self.total_distributed is not None:
            metadata["total_distributed"] = str(self.total_distributed)
        return metadata


@dataclass(frozen=True)
class MaterializationResult:
    run_id: str
    settlement_week: int
    state: str
    job_count: int
    ready_count: int
    skipped_count: int

    @classmethod
    def from_data(cls, data: Any, *, settlement_week: int) -> "MaterializationResult":
        row = _first_row(data)
        if row is None:
            raise SettlementStateError("settlement materialization RPC returned no result")
        return cls(
            run_id=str(row["run_id"]),
            settlement_week=parse_u64(
                row.get("settlement_week", settlement_week),
                field_name="settlement_week",
            ),
            state=str(row["state"]),
            job_count=int(row.get("job_count") or 0),
            ready_count=int(row.get("ready_count") or 0),
            skipped_count=int(row.get("skipped_count") or 0),
        )


class SettlementQueue:
    """Async wrapper around the settlement state-machine SQL contract."""

    def __init__(self, client: Any) -> None:
        self.client = client

    async def _rpc(self, name: str, params: dict[str, Any]) -> Any:
        return await asyncio.to_thread(lambda: self.client.rpc(name, params).execute())

    async def get_planning_cursor(self) -> int:
        try:
            response = await asyncio.to_thread(
                lambda: self.client.from_("settlement_planning_state")
                .select("bootstrap_state,last_materialized_week")
                .eq("id", 1)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise SettlementStateReadError(
                f"settlement planning state read failed: {exc}"
            ) from exc

        row = _first_row(_response_data(response))
        if row is None:
            raise SettlementStateReadError("settlement planning state row is missing")
        bootstrap_state = row.get("bootstrap_state")
        if bootstrap_state == "uninitialized" and row.get("last_materialized_week") is None:
            raise SettlementBootstrapRequired(
                "settlement planning requires authoritative chain bootstrap"
            )
        if bootstrap_state != "initialized" or row.get("last_materialized_week") is None:
            raise SettlementStateReadError("settlement planning state is internally inconsistent")
        try:
            return _parse_planning_cursor(row["last_materialized_week"])
        except ValueError as exc:
            raise SettlementStateReadError(
                f"settlement planning state is invalid: {exc}"
            ) from exc

    async def bootstrap(
        self,
        *,
        scope: "AuthoritativeVaultScope",
        latest_finalizable_week: int,
    ) -> int:
        evidence = scope.bootstrap_evidence()
        if len(evidence) != scope.counter_count:
            raise SettlementStateError("authoritative bootstrap evidence is incomplete")
        expected_cursor = safe_bootstrap_cursor(
            (vault["open_settlement_week"] for vault in evidence),
            latest_finalizable_week=latest_finalizable_week,
        )
        response = await self._rpc(
            "br_bootstrap_settlement_planning",
            {
                "p_counter_count": u64_string(scope.counter_count, field_name="counter_count"),
                "p_source_slot": u64_string(scope.source_slot, field_name="source_slot"),
                "p_latest_finalizable_week": u64_string(
                    latest_finalizable_week,
                    field_name="latest_finalizable_week",
                ),
                "p_vaults": evidence,
                "p_scope_evidence": scope.scope_evidence(),
            },
        )
        row = _first_row(_response_data(response))
        if row is None or row.get("bootstrap_state") != "initialized":
            raise SettlementStateError("settlement bootstrap RPC returned no initialized state")
        try:
            cursor = _parse_planning_cursor(row.get("last_materialized_week"))
        except ValueError as exc:
            raise SettlementStateError(
                f"settlement bootstrap RPC returned an invalid cursor: {exc}"
            ) from exc
        if cursor != expected_cursor:
            raise SettlementStateError(
                "settlement bootstrap RPC returned a cursor inconsistent with chain evidence"
            )
        return cursor

    async def reopen_zero_value_jobs(
        self, *, latest_finalizable_week: int,
        scope_evidence: Mapping[str, Any], jobs: Iterable[Mapping[str, Any]],
    ) -> int:
        response = await self._rpc("br_reopen_zero_value_settlement_jobs", {
            "p_latest_finalizable_week": u64_string(latest_finalizable_week, field_name="latest"),
            "p_scope_evidence": dict(scope_evidence),
            "p_jobs": [dict(job) for job in jobs],
        })
        return _rpc_count(_response_data(response))

    async def materialize_week(
        self,
        *,
        settlement_week: int,
        counter_count: int,
        source_slot: int,
        jobs: Iterable[Mapping[str, Any]],
        source_slot_min: Optional[int] = None,
        source_slot_max: Optional[int] = None,
        scope_evidence: Optional[Mapping[str, Any]] = None,
    ) -> MaterializationResult:
        serialized_jobs = [dict(job) for job in jobs]
        response = await self._rpc(
            "br_materialize_settlement_week",
            {
                "p_settlement_week": u64_string(
                    settlement_week,
                    field_name="settlement_week",
                ),
                "p_counter_count": u64_string(counter_count, field_name="counter_count"),
                "p_source_slot": u64_string(source_slot, field_name="source_slot"),
                "p_source_slot_min": u64_string(
                    source_slot_min if source_slot_min is not None else source_slot,
                    field_name="source_slot_min",
                ),
                "p_source_slot_max": u64_string(
                    source_slot_max if source_slot_max is not None else source_slot,
                    field_name="source_slot_max",
                ),
                "p_scope_evidence": dict(scope_evidence or {}),
                "p_jobs": serialized_jobs,
            },
        )
        result = MaterializationResult.from_data(
            _response_data(response),
            settlement_week=settlement_week,
        )
        expected_week = parse_u64(settlement_week, field_name="settlement_week")
        if result.settlement_week != expected_week:
            raise SettlementStateError(
                "settlement materialization RPC returned a different week"
            )
        return result

    async def reap_stale_leases(self) -> int:
        response = await self._rpc("br_reap_stale_settlement_leases", {})
        return _rpc_count(_response_data(response))

    async def retry_repairable_blocks(self, *, limit: int = 10) -> int:
        response = await self._rpc(
            "br_retry_repairable_settlement_jobs",
            {"p_limit": max(int(limit), 0)},
        )
        return _rpc_count(_response_data(response))

    async def claim(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        vault_id: Optional[int] = None,
    ) -> Optional[SettlementClaim]:
        response = await self._rpc(
            "br_claim_settlement_job",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": max(int(lease_seconds), 30),
                "p_vault_id": (
                    u64_string(vault_id, field_name="vault_id")
                    if vault_id is not None
                    else None
                ),
            },
        )
        row = _first_row(_response_data(response))
        if row is None:
            return None
        claim = SettlementClaim.from_row(row)
        if claim.state != "leased":
            raise SettlementStateError("submit claim RPC returned a non-leased job")
        return claim

    async def claim_preparation(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        vault_id: Optional[int] = None,
    ) -> Optional[SettlementClaim]:
        response = await self._rpc(
            "br_claim_settlement_preparation",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": max(int(lease_seconds), 30),
                "p_vault_id": (
                    u64_string(vault_id, field_name="vault_id")
                    if vault_id is not None
                    else None
                ),
            },
        )
        row = _first_row(_response_data(response))
        if row is None:
            return None
        claim = SettlementClaim.from_row(row)
        if claim.state != "preparing":
            raise SettlementStateError("preparation claim RPC returned an invalid state")
        return claim

    async def finish_preparation(
        self,
        claim: SettlementClaim,
        *,
        completed: bool,
        error: Optional[str],
        retry_seconds: int,
        result: Optional[Mapping[str, Any]] = None,
    ) -> None:
        await self._rpc(
            "br_finish_settlement_preparation",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_completed": completed,
                "p_error": error,
                "p_retry_seconds": max(int(retry_seconds), 1),
                "p_result": dict(result) if result is not None else None,
            },
        )

    async def persist_precondition_intent(
        self,
        claim: SettlementClaim,
        intent: Mapping[str, Any],
    ) -> dict[str, Any]:
        response = await self._rpc(
            "br_set_settlement_precondition_intent",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_intent": dict(intent),
            },
        )
        row = _first_row(_response_data(response))
        if row is None or not isinstance(row.get("precondition_intent"), Mapping):
            raise SettlementStateError("precondition intent RPC returned no durable intent")
        return dict(row["precondition_intent"])

    async def renew_lease(
        self,
        claim: SettlementClaim,
        *,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> None:
        await self._rpc(
            "br_renew_settlement_lease",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_lease_seconds": max(int(lease_seconds), 30),
            },
        )

    async def claim_reconciliation(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
        vault_id: Optional[int] = None,
    ) -> Optional[SettlementClaim]:
        response = await self._rpc(
            "br_claim_settlement_reconciliation",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": max(int(lease_seconds), 30),
                "p_vault_id": (
                    u64_string(vault_id, field_name="vault_id")
                    if vault_id is not None
                    else None
                ),
            },
        )
        row = _first_row(_response_data(response))
        if row is None:
            return None
        claim = SettlementClaim.from_row(row)
        if claim.state != "reconciling":
            raise SettlementStateError("reconciliation claim RPC returned an invalid state")
        return claim

    async def mark_submitted(self, claim: SettlementClaim, signature: str) -> None:
        if not signature:
            raise ValueError("submitted settlement must include a signature")
        await self._rpc(
            "br_mark_settlement_submitted",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_tx_signature": signature,
            },
        )

    async def mark_prepared(
        self,
        claim: SettlementClaim,
        signature: str,
        *,
        compute_unit_limit: int,
        transport_plan: Mapping[str, Any],
    ) -> None:
        if not signature:
            raise ValueError("prepared settlement must include a signature")
        if (
            isinstance(compute_unit_limit, bool)
            or not isinstance(compute_unit_limit, int)
            or not 1 <= compute_unit_limit <= 1_400_000
        ):
            raise ValueError(
                "prepared settlement compute unit limit must be an integer "
                "between 1 and 1400000"
            )
        try:
            lookup_table_address = str(transport_plan["lookup_table_address"])
            generation = int(
                parse_u64(
                    transport_plan["lookup_table_generation"],
                    field_name="lookup_table_generation",
                )
            )
            manifest = str(transport_plan["manifest_sha256"])
            last_extended_slot = u64_string(
                transport_plan["last_extended_slot"],
                field_name="last_extended_slot",
            )
            signed_bytes = int(
                parse_u64(
                    transport_plan["planned_serialized_bytes"],
                    field_name="planned_serialized_bytes",
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("prepared settlement transport plan is malformed") from exc
        if (
            not lookup_table_address
            or generation <= 0
            or len(manifest) != 64
            or any(character not in "0123456789abcdef" for character in manifest)
            or not 1 <= signed_bytes <= 900
        ):
            raise ValueError("prepared settlement transport plan is invalid")
        await self._rpc(
            "br_mark_settlement_prepared_v0",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_tx_signature": signature,
                "p_compute_unit_limit": compute_unit_limit,
                "p_lookup_table_address": lookup_table_address,
                "p_lookup_table_generation": generation,
                "p_transport_manifest_sha256": manifest,
                "p_lookup_table_last_extended_slot": last_extended_slot,
                "p_signed_transaction_bytes": signed_bytes,
            },
        )

    async def return_to_preparation(
        self,
        claim: SettlementClaim,
        *,
        error: str,
    ) -> None:
        await self._rpc(
            "br_return_settlement_to_preparation",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_error": error,
            },
        )

    async def mark_ambiguous(
        self,
        claim: SettlementClaim,
        *,
        error: str,
        error_class: str = "ambiguous_submit",
        tx_signature: Optional[str] = None,
    ) -> None:
        await self._rpc(
            "br_mark_settlement_ambiguous",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_error": error,
                "p_error_class": error_class,
                "p_tx_signature": tx_signature,
            },
        )

    async def mark_blocked(self, claim: SettlementClaim, *, error: str) -> None:
        await self._rpc(
            "br_mark_settlement_blocked",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_error": error,
            },
        )

    async def get_indexed_distribution(
        self,
        *,
        vault_id: int,
        settlement_week: int,
    ) -> Optional[dict[str, Any]]:
        response = await asyncio.to_thread(
            lambda: self.client.from_("indexed_epoch_distributions")
            .select("*")
            .eq("vault_id", vault_id)
            .eq("epoch", settlement_week)
            .order("slot", desc=True)
            .limit(1)
            .execute()
        )
        return _first_row(_response_data(response))

    async def get_lifecycle_signature(
        self,
        claim: SettlementClaim,
    ) -> Optional[str]:
        if not claim.submit_started_at:
            return None

        def execute() -> Any:
            return (
                self.client.from_("tx_lifecycle")
                .select("signature,status,created_at")
                .eq("tx_type", "epoch_distribute")
                .eq("reference_type", "vault")
                .eq("reference_id", str(claim.vault_id))
                .gte("created_at", claim.submit_started_at)
                .in_("status", ["submitted", "landed", "confirmed", "finalized"])
                .order("created_at", desc=True)
                .limit(1)
                .execute()
            )

        response = await asyncio.to_thread(execute)
        row = _first_row(_response_data(response))
        return str(row["signature"]) if row and row.get("signature") else None

    async def get_reconciliation_slot_floor(self, claim: SettlementClaim) -> int:
        response = await self._rpc(
            "br_get_settlement_reconciliation_slot_floor",
            {"p_job_id": claim.id, "p_lease_token": claim.lease_token},
        )
        # The RPC returns an exact decimal string, including "0" for a stored
        # legacy NULL. A missing response is a read failure, never a zero floor.
        return parse_u64(_response_data(response), field_name="absence_slot_floor")

    async def finish_reconciliation(
        self,
        claim: SettlementClaim,
        *,
        decision: str,
        evidence: Mapping[str, Any],
        signature_state: str,
        chain_commitment: str,
        observed_open_week: Optional[int],
        indexed_tx_signature: Optional[str],
        indexed_signature_finalized: bool,
        recovered_tx_signature: Optional[str],
        error: Optional[str],
        retry_seconds: int,
    ) -> None:
        await self._rpc(
            "br_finish_settlement_reconciliation",
            {
                "p_job_id": claim.id,
                "p_lease_token": claim.lease_token,
                "p_decision": decision,
                "p_evidence": dict(evidence),
                "p_signature_state": signature_state,
                "p_chain_commitment": chain_commitment,
                "p_observed_open_week": (
                    u64_string(observed_open_week, field_name="observed_open_week")
                    if observed_open_week is not None
                    else None
                ),
                "p_indexed_tx_signature": indexed_tx_signature,
                "p_indexed_signature_finalized": indexed_signature_finalized,
                "p_recovered_tx_signature": recovered_tx_signature,
                "p_error": error,
                "p_retry_seconds": max(int(retry_seconds), 1),
            },
        )

    async def claim_notification(
        self,
        *,
        worker_id: str,
        lease_seconds: int = DEFAULT_LEASE_SECONDS,
    ) -> Optional[SettlementNotificationEvent]:
        response = await self._rpc(
            "br_claim_settlement_notification",
            {
                "p_worker_id": worker_id,
                "p_lease_seconds": max(int(lease_seconds), 30),
            },
        )
        row = _first_row(_response_data(response))
        return SettlementNotificationEvent.from_row(row) if row is not None else None

    async def mark_notification_delivered(
        self,
        event: SettlementNotificationEvent,
    ) -> None:
        await self._rpc(
            "br_finish_settlement_notification",
            {
                "p_outbox_id": event.id,
                "p_lease_token": event.lease_token,
                "p_delivered": True,
                "p_error": None,
            },
        )

    async def mark_notification_retry(
        self,
        event: SettlementNotificationEvent,
        *,
        error: str,
    ) -> None:
        await self._rpc(
            "br_finish_settlement_notification",
            {
                "p_outbox_id": event.id,
                "p_lease_token": event.lease_token,
                "p_delivered": False,
                "p_error": error,
            },
        )

    async def status(self) -> dict[str, Any]:
        response = await asyncio.to_thread(
            lambda: self.client.from_("settlement_jobs")
            .select("state,dung_to_mint,blocked_reason,last_error,created_at")
            .execute()
        )
        rows = _response_data(response) or []
        preparation_states = {
            "precondition_pending",
            "preparing",
            "precondition_retry",
        }
        active_states = preparation_states | {
            "ready",
            "leased",
            "submitted",
            "reconciling",
            "retry_wait",
        }
        blocked_rows = [row for row in rows if row.get("state") == "blocked"]
        preparation_rows = [
            row for row in rows if row.get("state") in preparation_states
        ]
        reconciliation_states = {"submitted", "reconciling", "retry_wait"}
        reconciliation_rows = [
            row for row in rows if row.get("state") in reconciliation_states
        ]
        review_rows = [
            row for row in rows if row.get("state") == "advanced_unproven"
        ]
        blocked_reasons = sorted({
            str(row.get("blocked_reason") or "unspecified settlement block")
            for row in blocked_rows
        })
        blocked_times = sorted(
            str(row["created_at"])
            for row in blocked_rows
            if row.get("created_at")
        )
        pending_dung = sum(
            parse_u64(row.get("dung_to_mint", 0), field_name="dung_to_mint")
            for row in rows
            if row.get("state") in active_states
        )
        return {
            "pending": sum(1 for row in rows if row.get("state") in active_states),
            "pending_dung": str(pending_dung),
            "confirmed": sum(1 for row in rows if row.get("state") == "confirmed"),
            "advanced_unproven": sum(
                1 for row in rows if row.get("state") == "advanced_unproven"
            ),
            "blocked": len(blocked_rows),
            "blocked_reasons": blocked_reasons,
            "oldest_blocked_at": blocked_times[0] if blocked_times else None,
            "preconditions_pending": len(preparation_rows),
            "precondition_reasons": sorted({
                str(row.get("last_error") or row.get("state"))
                for row in preparation_rows
            }),
            "reconciliation_pending": len(reconciliation_rows),
            "review_required": len(review_rows),
            "healthy": not (
                blocked_rows
                or preparation_rows
                or reconciliation_rows
                or review_rows
            ),
        }

    async def has_unfinished_jobs(self, *, settlement_week: int) -> bool:
        active_states = [
            "precondition_pending",
            "preparing",
            "precondition_retry",
            "ready",
            "leased",
            "submitted",
            "reconciling",
            "retry_wait",
            "blocked",
        ]

        def execute() -> Any:
            return (
                self.client.from_("settlement_jobs")
                .select("id")
                .lte("settlement_week", settlement_week)
                .eq("legacy_evidence_only", False)
                .in_("state", active_states)
                .limit(1)
                .execute()
            )

        response = await asyncio.to_thread(execute)
        return bool(_response_data(response))
