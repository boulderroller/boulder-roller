from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from supabase import Client

from .repositories import _build_supabase_client
from .services.account_deletion import (
    AccountDeletionBlocker,
    AccountDeletionRequest,
)


class ComplianceRepository:
    """Repository for security and compliance operations."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or _build_supabase_client()

    async def _run(self, func):
        return await asyncio.to_thread(func)

    async def _select(
        self,
        table: str,
        filters: Optional[Dict[str, Any]] = None,
        order: Optional[tuple[str, bool]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        def _op():
            query = self._client.table(table).select("*")
            for key, value in (filters or {}).items():
                query = query.eq(key, value)
            if order:
                column, desc = order
                query = query.order(column, desc=desc)
            if limit:
                query = query.limit(limit)
            return query.execute()

        try:
            response = await self._run(_op)
            return getattr(response, "data", None) or []
        except Exception:
            return []

    async def _select_one(self, table: str, filters: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        rows = await self._select(table, filters, limit=1)
        return rows[0] if rows else None

    async def _strict_select(
        self,
        table: str,
        *,
        columns: str = "*",
        filters: Optional[Dict[str, Any]] = None,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Read deletion authority without converting outages into empty state."""

        def _op():
            query = self._client.table(table).select(columns)
            for key, value in (filters or {}).items():
                query = query.eq(key, value)
            if limit is not None:
                query = query.limit(limit)
            return query.execute()

        response = await self._run(_op)
        data = getattr(response, "data", None)
        if not isinstance(data, list):
            raise RuntimeError(f"{table} deletion authority returned no rows payload")
        return [dict(row) for row in data]

    @staticmethod
    def _first_rpc_row(response: Any, *, operation: str) -> Dict[str, Any]:
        data = getattr(response, "data", None)
        if isinstance(data, list) and data and isinstance(data[0], dict):
            return dict(data[0])
        if isinstance(data, dict):
            return dict(data)
        raise RuntimeError(f"{operation} returned no durable request row")

    async def log_audit_event(
        self,
        action: str,
        user_id: Optional[UUID] = None,
        target_type: Optional[str] = None,
        target_id: Optional[UUID] = None,
        metadata: Optional[Dict[str, Any]] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
    ) -> Optional[str]:
        payload = {
            "action": action,
            "user_id": str(user_id) if user_id else None,
            "target_type": target_type,
            "target_id": str(target_id) if target_id else None,
            "metadata": metadata or {},
            "ip_address": ip_address,
            "user_agent": user_agent,
        }

        try:
            response = await self._run(lambda: self._client.table("audit_log").insert(payload).execute())
            data = getattr(response, "data", None) or []
            return str(data[0].get("id")) if data else None
        except Exception:
            return None

    async def get_user_audit_log(self, user_id: UUID, limit: int = 100) -> List[Dict[str, Any]]:
        return await self._select(
            "audit_log",
            filters={"user_id": str(user_id)},
            order=("created_at", True),
            limit=limit,
        )

    async def export_user_data(self, user_id: UUID) -> Dict[str, Any]:
        from .services.data_export import export_account

        return await export_account(self._client, self._run, str(user_id))

    async def get_deletion_database_blockers(
        self,
        user_id: str,
        wallet: str,
    ) -> List[Dict[str, Any]]:
        """Read all database blockers through the schema-aware server RPC."""
        response = await self._run(
            lambda: self._client.rpc(
                "br_account_deletion_db_blockers",
                {"p_user_id": user_id, "p_wallet": wallet},
            ).execute()
        )
        data = getattr(response, "data", None)
        if not isinstance(data, list) or any(not isinstance(row, dict) for row in data):
            raise RuntimeError("Deletion blocker authority returned a malformed payload")
        return [dict(row) for row in data]

    async def create_deletion_request(
        self,
        *,
        request_id: UUID,
        user_id: UUID,
        wallet: str,
        unuploaded_rides_acknowledged: bool,
        status_token_hash: str,
        preflight_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "create_account_deletion_request",
                {
                    "p_request_id": str(request_id),
                    "p_user_id": str(user_id),
                    "p_wallet": wallet,
                    "p_unuploaded_rides_acknowledged": unuploaded_rides_acknowledged,
                    "p_status_token_hash": status_token_hash,
                    "p_preflight_snapshot": preflight_snapshot,
                },
            ).execute()
        )
        return self._first_rpc_row(response, operation="create_account_deletion_request")

    async def claim_for_processing(self, request_id: str) -> Optional[AccountDeletionRequest]:
        worker_id = uuid4()
        response = await self._run(
            lambda: self._client.rpc(
                "claim_account_deletion_request",
                {
                    "p_request_id": request_id,
                    "p_worker_id": str(worker_id),
                    "p_lease_seconds": 300,
                },
            ).execute()
        )
        data = getattr(response, "data", None)
        if not data:
            return None
        row = self._first_rpc_row(response, operation="claim_account_deletion_request")
        wallet = str(row.get("wallet") or "")
        if not wallet:
            raise RuntimeError("Claimed deletion request no longer has a preflight wallet")
        raw_paths = row.get("storage_paths") or []
        if not isinstance(raw_paths, list):
            raise RuntimeError("Claimed deletion request has malformed storage paths")
        lease_token = str(row.get("worker_lease_token") or "")
        if not lease_token:
            raise RuntimeError("Claimed deletion request has no worker lease token")
        return AccountDeletionRequest(
            request_id=str(row["id"]),
            user_id=str(row["user_id"]),
            wallet=wallet,
            status=str(row["status"]),
            unuploaded_rides_acknowledged=bool(row.get("unuploaded_rides_acknowledged")),
            storage_paths=tuple(str(path) for path in raw_paths if path),
            lease_token=lease_token,
        )

    async def mark_blocked(
        self,
        request: AccountDeletionRequest,
        blockers: List[AccountDeletionBlocker] | tuple[AccountDeletionBlocker, ...],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_account_deletion_blocked",
                {
                    "p_request_id": request.request_id,
                    "p_blockers": [blocker.as_dict() for blocker in blockers],
                    "p_lease_token": request.lease_token,
                },
            ).execute()
        )
        return self._first_rpc_row(response, operation="mark_account_deletion_blocked")

    async def mark_failed(
        self,
        request: AccountDeletionRequest,
        *,
        failure_code: str,
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "fail_account_deletion_request",
                {
                    "p_request_id": request.request_id,
                    "p_lease_token": request.lease_token,
                    "p_failure_code": failure_code,
                },
            ).execute()
        )
        return self._first_rpc_row(response, operation="fail_account_deletion_request")

    async def mark_needs_support(
        self,
        request: AccountDeletionRequest,
        blockers: List[AccountDeletionBlocker] | tuple[AccountDeletionBlocker, ...],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "support_account_deletion_request",
                {
                    "p_request_id": request.request_id,
                    "p_blockers": [blocker.as_dict() for blocker in blockers],
                    "p_lease_token": request.lease_token,
                },
            ).execute()
        )
        return self._first_rpc_row(response, operation="support_account_deletion_request")

    async def mark_dispatch_failed(self, request_id: str) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "fail_account_deletion_dispatch",
                {"p_request_id": request_id},
            ).execute()
        )
        data = getattr(response, "data", None)
        if data:
            return self._first_rpc_row(
                response,
                operation="fail_account_deletion_dispatch",
            )

        # The durable worker can claim the queued row between enqueue failure
        # and this fallback RPC. That race is success, not an HTTP 500.
        current = await self.get_deletion_request(request_id)
        if current:
            return current
        raise RuntimeError("fail_account_deletion_dispatch lost its durable request row")

    async def renew_lease(self, request: AccountDeletionRequest) -> None:
        response = await self._run(
            lambda: self._client.rpc(
                "renew_account_deletion_lease",
                {
                    "p_request_id": request.request_id,
                    "p_lease_token": request.lease_token,
                    "p_lease_seconds": 300,
                },
            ).execute()
        )
        self._first_rpc_row(response, operation="renew_account_deletion_lease")

    async def authorize_storage_deletion(
        self,
        request: AccountDeletionRequest,
        *,
        preflight_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Cross the atomic database gate before any storage destruction."""
        response = await self._run(
            lambda: self._client.rpc(
                "authorize_account_deletion_storage",
                {
                    "p_request_id": request.request_id,
                    "p_lease_token": request.lease_token,
                    "p_preflight_snapshot": preflight_snapshot,
                },
            ).execute()
        )
        return self._first_rpc_row(
            response,
            operation="authorize_account_deletion_storage",
        )

    async def record_storage_receipt(
        self,
        request: AccountDeletionRequest,
        *,
        path: str,
        outcome: str,
    ) -> None:
        response = await self._run(
            lambda: self._client.rpc(
                "record_account_deletion_storage_receipt",
                {
                    "p_request_id": request.request_id,
                    "p_lease_token": request.lease_token,
                    "p_path": path,
                    "p_outcome": outcome,
                },
            ).execute()
        )
        self._first_rpc_row(response, operation="record_account_deletion_storage_receipt")

    async def mark_storage_removed(
        self,
        request: AccountDeletionRequest,
        *,
        preflight_snapshot: Dict[str, Any],
    ) -> None:
        response = await self._run(
            lambda: self._client.rpc(
                "mark_account_deletion_storage_removed",
                {
                    "p_request_id": request.request_id,
                    "p_lease_token": request.lease_token,
                    "p_preflight_snapshot": preflight_snapshot,
                },
            ).execute()
        )
        self._first_rpc_row(response, operation="mark_account_deletion_storage_removed")

    async def finalize_anonymization(
        self,
        request: AccountDeletionRequest,
    ) -> Dict[str, Any]:
        # The DB suspends affected exports under the publisher's asset lock.
        # Cleanup precedes the existing atomic finalizer; a missing volume or
        # receipt failure leaves deletion retryable, never falsely completed.
        import os
        from .services.stage1_keeper_erasure import redact_export
        prepared = await self._run(lambda: self._client.rpc(
            "stage1_keeper_prepare_erasure", {
                "p_request_id": request.request_id, "p_lease_token": request.lease_token,
            }).execute())
        outcome = prepared.data
        if not isinstance(outcome, dict) or not isinstance(outcome.get("exports"), list) or "request" not in outcome:
            raise RuntimeError("Keeper erasure preparation returned a malformed outcome")
        if outcome["request"] is not None:
            row = outcome["request"]
            if not isinstance(row, dict) or row.get("status") != "needs_support" or str(row.get("id")) != str(request.request_id):
                raise RuntimeError("Keeper erasure preparation returned an invalid request")
            return row
        for entry in outcome["exports"]:
            def redact_entry():
                params = {"p_request_id": request.request_id, "p_lease_token": request.lease_token,
                          "p_job_id": entry["job_id"], "p_digest": entry["digest"]}
                boundary = entry.get("kind") == "boundary"
                prefix = "stage1_boundary" if boundary else "stage1_keeper"
                root = "STAGE1_BOUNDARY_EXPORT_DIR" if boundary else "STAGE1_KEEPER_EXPORT_DIR"
                return redact_export(entry, os.environ[root],
                    validate=lambda: self._client.rpc(prefix + "_validate_erasure", {
                        **params, "p_payload": entry["payload"],
                    }).execute(),
                    record=lambda sha: self._client.rpc(prefix + "_record_erasure", {
                        **params, "p_redacted_digest": sha,
                    }).execute())
            await self._run(redact_entry)
        response = await self._run(
            lambda: self._client.rpc(
                "finalize_account_anonymization",
                {
                    "p_request_id": request.request_id,
                    "p_user_id": request.user_id,
                    "p_lease_token": request.lease_token,
                },
            ).execute()
        )
        row = self._first_rpc_row(response, operation="finalize_account_anonymization")
        return row

    async def get_deletion_request(self, request_id: UUID | str) -> Optional[Dict[str, Any]]:
        rows = await self._strict_select(
            "deletion_requests",
            filters={"id": str(request_id)},
            limit=1,
        )
        return rows[0] if rows else None

    async def prepare_deletion_retry(
        self,
        request_id: str,
        *,
        preflight_snapshot: Dict[str, Any],
    ) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.rpc(
                "retry_account_deletion_request",
                {
                    "p_request_id": request_id,
                    "p_preflight_snapshot": preflight_snapshot,
                },
            ).execute()
        )
        return self._first_rpc_row(response, operation="retry_account_deletion_request")

    async def list_recoverable_deletion_requests(self, limit: int = 100) -> List[str]:
        response = await self._run(
            lambda: self._client.rpc(
                "list_recoverable_account_deletions",
                {"p_limit": limit},
            ).execute()
        )
        data = getattr(response, "data", None)
        if not isinstance(data, list):
            raise RuntimeError("Recoverable deletion request scan returned no rows payload")
        return [str(row["id"]) for row in data if isinstance(row, dict) and row.get("id")]

    async def get_recent_audit_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        return await self._select(
            "audit_log",
            order=("created_at", True),
            limit=limit,
        )

    async def get_admin_role(self, user_id: UUID) -> Optional[str]:
        record = await self._select_one("admin_users", {"user_id": str(user_id)})
        if record:
            return record.get("role") or "admin"
        return None

    async def list_system_controls(self) -> List[Dict[str, Any]]:
        return await self._select("system_controls", order=("key", False))
