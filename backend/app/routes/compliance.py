from __future__ import annotations

import base64
import json
import logging
from datetime import datetime
from typing import Any, Awaitable, Callable, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import Response, StreamingResponse
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..compliance_repository import ComplianceRepository
from ..services.data_export import DataExportError, export_ride
from ..dependencies import AuthenticatedUser, get_current_user
from ..middleware.rate_limiter import rate_limit
from ..services.account_deletion import (
    AccountDeletionAuthorityReader,
    AccountDeletionBlocker,
    AccountDeletionPreflight,
    DeletionBlockerCode,
    account_deletion_preflight_snapshot,
    account_deletion_status_token_matches,
    evaluate_account_deletion_preflight,
    hash_account_deletion_status_token,
)
from ..services.account_deletion_factory import (
    build_account_deletion_authority_reader,
)

logger = logging.getLogger(__name__)

class CompliancePrivateNoStoreRoute(APIRoute):
    """Keep lifecycle capabilities and account state out of shared caches."""

    def get_route_handler(self) -> Callable[[Request], Awaitable[Response]]:
        route_handler = super().get_route_handler()

        async def private_no_store(request: Request) -> Response:
            try:
                response = await route_handler(request)
            except HTTPException as exc:
                exc.headers = {
                    **(exc.headers or {}),
                    "Cache-Control": "private, no-store",
                }
                raise
            response.headers["Cache-Control"] = "private, no-store"
            return response

        return private_no_store


router = APIRouter(
    prefix="/compliance",
    tags=["compliance"],
    route_class=CompliancePrivateNoStoreRoute,
)


class ExportResponse(BaseModel):
    status: str
    message: str
    download_url: Optional[str] = None


class DeletionCreateRequest(BaseModel):
    request_id: UUID
    status_token: str = Field(min_length=43, max_length=43, pattern=r"^[A-Za-z0-9_-]+$")
    unuploaded_rides_acknowledged: bool

    @field_validator("status_token")
    @classmethod
    def validate_status_token(cls, value: str) -> str:
        try:
            decoded = base64.urlsafe_b64decode(value + "=")
        except Exception as exc:
            raise ValueError("status_token must be base64url encoded") from exc
        if len(decoded) != 32 or base64.urlsafe_b64encode(decoded).decode().rstrip("=") != value:
            raise ValueError("status_token must encode exactly 32 random bytes")
        return value


class DeletionRetryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class DeletionBlockerResponse(BaseModel):
    code: str
    category: str
    asset: Optional[str] = None
    amount_base_units: Optional[str] = None
    count: Optional[int] = None
    source: Optional[str] = None
    action: Optional[str] = None


class DeletionPreflightResponse(BaseModel):
    contract_version: str = "account-deletion.v1"
    allowed: bool
    available: bool
    blockers: list[DeletionBlockerResponse]
    checked_at: datetime


class DeletionStatusResponse(BaseModel):
    contract_version: str = "account-deletion.v1"
    request_id: str
    status: str
    requested_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    blockers: list[DeletionBlockerResponse]
    failure_code: Optional[str] = None
    retryable: bool
    attempt_count: int


class AccountDeletionDispatcher:
    """Immediate dispatch is latency only; the durable row remains queue truth."""

    def enqueue(self, request_id: str) -> None:
        from ..tasks import process_account_deletion

        process_account_deletion.delay(request_id=request_id)


def get_account_deletion_repository() -> ComplianceRepository:
    return ComplianceRepository()


def get_account_deletion_preflight_reader(
    repository: ComplianceRepository = Depends(get_account_deletion_repository),
) -> AccountDeletionAuthorityReader:
    return build_account_deletion_authority_reader(repository)


def get_account_deletion_dispatcher() -> AccountDeletionDispatcher:
    return AccountDeletionDispatcher()


def _blockers(blockers: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for blocker in blockers or []:
        if isinstance(blocker, AccountDeletionBlocker):
            result.append(blocker.as_dict())
        elif isinstance(blocker, dict):
            result.append(dict(blocker))
    return result


def _preflight_payload(preflight: AccountDeletionPreflight) -> dict[str, Any]:
    return account_deletion_preflight_snapshot(preflight)


def _translate_deletion_lifecycle_exception(exc: Exception) -> None:
    """Expose stable conflict codes without leaking database exception text."""
    message = str(exc).lower()
    conflicts = {
        "account_deletion_request_already_active": "request_already_active",
        "account_deletion_user_unavailable": "account_unavailable",
        "account_deletion_request_id_conflict": "request_id_conflict",
        "account_deletion_retry_unavailable": "retry_unavailable",
        "account_deletion_retry_requires_support": "retry_requires_support",
    }
    for marker, code in conflicts.items():
        if marker in message:
            raise HTTPException(status_code=409, detail={"code": code}) from exc
    if "23505" in message and "deletion" in message:
        raise HTTPException(
            status_code=409,
            detail={"code": "request_already_active"},
        ) from exc


def _status_payload(
    row: dict[str, Any],
) -> dict[str, Any]:
    reported_status = str(row.get("status") or "failed_retryable")
    completed_at = row.get("completed_at")
    if reported_status == "completed" and not row.get("completion_verified_at"):
        reported_status = "legacy_unverified"
    if reported_status != "completed" or not row.get("completion_verified_at"):
        completed_at = None
    return {
        "contract_version": "account-deletion.v1",
        "request_id": str(row["id"]),
        "status": reported_status,
        "requested_at": row.get("requested_at"),
        "updated_at": row.get("updated_at"),
        "completed_at": completed_at,
        "blockers": _blockers(row.get("blockers")),
        "failure_code": row.get("failure_code"),
        "retryable": bool(row.get("retryable")),
        "attempt_count": int(row.get("attempt_count") or 0),
    }


async def _read_authorized_request(
    *,
    repository: ComplianceRepository,
    request_id: str,
    status_token: Optional[str],
) -> dict[str, Any]:
    try:
        parsed_request_id = UUID(request_id)
    except ValueError:
        raise HTTPException(status_code=404, detail="Deletion request not found") from None
    row = await repository.get_deletion_request(parsed_request_id)
    if not row or not account_deletion_status_token_matches(
        status_token or "",
        str(row.get("status_token_hash") or ""),
    ):
        raise HTTPException(status_code=404, detail="Deletion request not found")
    return row


@router.get("/export", response_model=ExportResponse)
@rate_limit(category="general")
async def export_user_data(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Export all user data for GDPR compliance."""
    repo = ComplianceRepository()
    user_uuid = UUID(current_user.user_id)

    await repo.log_audit_event(
        action="data_export_requested",
        user_id=user_uuid,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    try:
        data = await repo.export_user_data(user_uuid)
    except DataExportError as exc:
        logger.error("Account export failed dataset=%s reason=%s", exc.dataset, exc.reason)
        # Existing Settings failure copy. Never return a completed envelope or
        # a partial download when any dataset or stored object could not load.
        raise HTTPException(status_code=503, detail="Could not export data") from None

    def serialize(obj):
        if isinstance(obj, datetime):
            return obj.isoformat()
        if isinstance(obj, UUID):
            return str(obj)
        return obj

    payload = json.dumps(data, default=serialize)
    encoded = base64.b64encode(payload.encode()).decode()

    return ExportResponse(
        status="completed",
        message="Data export completed. Download will begin shortly.",
        download_url=f"data:application/json;base64,{encoded}",
    )


@router.get("/export/rides/{ride_id}/data")
@rate_limit(category="general")
async def export_ride_data(
    ride_id: UUID,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Full ride/GPS/stream evidence; ownership is independent of social visibility."""
    repo = ComplianceRepository()
    try:
        data = await export_ride(repo._client, repo._run, current_user.user_id, str(ride_id))
    except DataExportError as exc:
        logger.error("Ride export failed dataset=%s reason=%s", exc.dataset, exc.reason)
        raise HTTPException(status_code=503, detail="Could not export data") from exc
    if data is None:
        raise HTTPException(status_code=404, detail="Ride not found")
    async def content():
        try:
            async for chunk in data:
                yield chunk
        except DataExportError as exc:
            logger.error("Ride export stream failed dataset=%s reason=%s", exc.dataset, exc.reason)
            raise  # An interrupted download must not end as a valid partial JSON export.
    return StreamingResponse(content(), media_type="application/json",
                    headers={"Content-Disposition": f'attachment; filename="ride-{ride_id}.json"'})


@router.get("/account/preflight", response_model=DeletionPreflightResponse)
@rate_limit(category="general")
async def get_account_deletion_preflight(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    reader: AccountDeletionAuthorityReader = Depends(get_account_deletion_preflight_reader),
):
    del request
    snapshot = await reader.read(
        user_id=current_user.user_id,
        wallet=current_user.wallet,
    )
    return _preflight_payload(evaluate_account_deletion_preflight(snapshot))


@router.delete(
    "/account",
    response_model=DeletionStatusResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
@rate_limit(category="general")
async def delete_account(
    request: Request,
    payload: DeletionCreateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repository: ComplianceRepository = Depends(get_account_deletion_repository),
    reader: AccountDeletionAuthorityReader = Depends(get_account_deletion_preflight_reader),
    dispatcher: AccountDeletionDispatcher = Depends(get_account_deletion_dispatcher),
):
    """Create an idempotent deletion request; never claim synchronous completion."""
    if not payload.unuploaded_rides_acknowledged:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": DeletionBlockerCode.UNUPLOADED_RIDES_UNACKNOWLEDGED.value,
                "blockers": [
                    AccountDeletionBlocker(
                        code=DeletionBlockerCode.UNUPLOADED_RIDES_UNACKNOWLEDGED,
                        category="recording",
                        action="review_recordings",
                    ).as_dict()
                ],
            },
        )

    snapshot = await reader.read(
        user_id=current_user.user_id,
        wallet=current_user.wallet,
    )
    preflight = evaluate_account_deletion_preflight(snapshot)
    user_uuid = UUID(current_user.user_id)

    try:
        row = await repository.create_deletion_request(
            request_id=payload.request_id,
            user_id=user_uuid,
            wallet=current_user.wallet,
            unuploaded_rides_acknowledged=True,
            status_token_hash=hash_account_deletion_status_token(payload.status_token),
            preflight_snapshot=account_deletion_preflight_snapshot(preflight),
        )
    except Exception as exc:
        _translate_deletion_lifecycle_exception(exc)
        raise
    if not account_deletion_status_token_matches(
        payload.status_token,
        str(row.get("status_token_hash") or ""),
    ):
        raise HTTPException(status_code=409, detail={"code": "request_id_conflict"})

    await repository.log_audit_event(
        action="account_deletion_requested",
        user_id=user_uuid,
        target_type="user",
        target_id=user_uuid,
        metadata={"request_id": str(row["id"])},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    if str(row.get("status")) == "queued":
        try:
            dispatcher.enqueue(str(row["id"]))
        except Exception:
            row = await repository.mark_dispatch_failed(str(row["id"]))

    return _status_payload(row)


@router.get("/deletion-status/{request_id}", response_model=DeletionStatusResponse)
@rate_limit(category="general")
async def get_deletion_status(
    request: Request,
    request_id: str,
    status_token: Optional[str] = Header(None, alias="X-Account-Deletion-Token"),
    repository: ComplianceRepository = Depends(get_account_deletion_repository),
):
    del request
    row = await _read_authorized_request(
        repository=repository,
        request_id=request_id,
        status_token=status_token,
    )
    return _status_payload(row)


@router.post(
    "/deletion-status/{request_id}/retry",
    response_model=DeletionStatusResponse,
)
@rate_limit(category="general")
async def retry_deletion(
    request: Request,
    request_id: str,
    payload: DeletionRetryRequest,
    status_token: Optional[str] = Header(None, alias="X-Account-Deletion-Token"),
    repository: ComplianceRepository = Depends(get_account_deletion_repository),
    reader: AccountDeletionAuthorityReader = Depends(get_account_deletion_preflight_reader),
    dispatcher: AccountDeletionDispatcher = Depends(get_account_deletion_dispatcher),
):
    del request, payload
    row = await _read_authorized_request(
        repository=repository,
        request_id=request_id,
        status_token=status_token,
    )
    if str(row.get("status")) not in {"blocked", "failed_retryable"}:
        return _status_payload(row)
    wallet = str(row.get("wallet") or "")
    user_id = str(row.get("user_id") or "")
    if not wallet or not user_id:
        raise HTTPException(status_code=409, detail={"code": "retry_unavailable"})
    snapshot = await reader.read(user_id=user_id, wallet=wallet)
    preflight = evaluate_account_deletion_preflight(snapshot)
    if any(
        blocker.code == DeletionBlockerCode.POLICY_REVIEW_REQUIRED
        for blocker in preflight.blockers
    ):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "retry_requires_support",
                "blockers": _blockers(preflight.blockers),
            },
        )
    try:
        row = await repository.prepare_deletion_retry(
            request_id,
            preflight_snapshot=account_deletion_preflight_snapshot(preflight),
        )
    except Exception as exc:
        _translate_deletion_lifecycle_exception(exc)
        raise
    if str(row.get("status")) == "queued":
        try:
            dispatcher.enqueue(request_id)
        except Exception:
            row = await repository.mark_dispatch_failed(request_id)
    return _status_payload(row)
