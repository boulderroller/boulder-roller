"""Mobile operability endpoints: crash-diagnostics ingest + push devices.

Bead boulderroller-v2-k7387 (iOS halves: odmi6.8 / odmi6.14).

POST   /mobile/diagnostics          — authenticated, rate-limited, size-capped
                                      MetricKit envelope ingest ($0 crash
                                      reporting; symbolication runbook:
                                      docs/runbooks/IOS_CRASH_SYMBOLICATION.md)
POST   /mobile/push/devices         — upsert this install's APNs token
DELETE /mobile/push/devices/{id}    — remove it (sign-out)
"""
from __future__ import annotations

import json
import logging
from datetime import datetime
from typing import Any, Optional

from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..dependencies import AuthenticatedUser, get_current_user
from ..middleware.rate_limiter import rate_limit
from ..repositories.mobile_ops import MobileOpsRepository, create_mobile_ops_repository

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/mobile", tags=["mobile"])


def get_mobile_ops_repository() -> MobileOpsRepository:
    return create_mobile_ops_repository()


# ---------------------------------------------------------------------------
# Crash diagnostics ingest
# ---------------------------------------------------------------------------

# Caps mirrored by the iOS client queue (DiagnosticQueue/DiagnosticUploader):
# at most 4 envelopes per request, 512 KiB per envelope serialized.
MAX_DIAGNOSTICS_PER_REQUEST = 4
MAX_DIAGNOSTIC_BYTES = 512 * 1024

ALLOWED_DIAGNOSTIC_TYPES = {
    "crash",
    "hang",
    "cpu_exception",
    "disk_write_exception",
    "app_launch",
    # DEBUG-only pipeline verification envelope — honestly labeled synthetic.
    "debug_forced_test",
}


class DiagnosticsIngestRequest(BaseModel):
    diagnostics: list[dict[str, Any]] = Field(..., min_length=1)


class DiagnosticsIngestResponse(BaseModel):
    accepted: int


def _parse_captured_at(raw: Any) -> Optional[str]:
    if not isinstance(raw, str) or not raw:
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).isoformat()
    except ValueError:
        return None


@router.post("/diagnostics", response_model=DiagnosticsIngestResponse)
@rate_limit(category="mobile_diagnostics")
async def ingest_diagnostics(
    request: Request,
    payload: DiagnosticsIngestRequest = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: MobileOpsRepository = Depends(get_mobile_ops_repository),
) -> DiagnosticsIngestResponse:
    if len(payload.diagnostics) > MAX_DIAGNOSTICS_PER_REQUEST:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail={
                "error": "too_many_diagnostics",
                "message": f"At most {MAX_DIAGNOSTICS_PER_REQUEST} diagnostics per request",
            },
        )

    rows: list[dict[str, Any]] = []
    for envelope in payload.diagnostics:
        serialized = json.dumps(envelope)
        if len(serialized) > MAX_DIAGNOSTIC_BYTES:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail={
                    "error": "diagnostic_too_large",
                    "message": f"Each diagnostic must serialize under {MAX_DIAGNOSTIC_BYTES} bytes",
                },
            )
        diagnostic_type = str(envelope.get("diagnostic_type") or "")
        if diagnostic_type not in ALLOWED_DIAGNOSTIC_TYPES:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "unknown_diagnostic_type",
                    "message": f"diagnostic_type {diagnostic_type!r} is not accepted",
                },
            )
        diagnostic_payload = envelope.get("payload")
        if not isinstance(diagnostic_payload, dict) or not diagnostic_payload:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "error": "missing_payload",
                    "message": "Each diagnostic needs a non-empty payload object",
                },
            )
        rows.append(
            {
                "wallet": current_user.wallet,
                "device_id": current_user.device_id,
                "schema_version": int(envelope.get("schema") or 1),
                "diagnostic_type": diagnostic_type,
                "captured_at": _parse_captured_at(envelope.get("captured_at")),
                "app_version": str(envelope.get("app_version") or "")[:64] or None,
                "build_number": str(envelope.get("build_number") or "")[:64] or None,
                "os_version": str(envelope.get("os_version") or "")[:128] or None,
                "device_model": str(envelope.get("device_model") or "")[:64] or None,
                "payload": diagnostic_payload,
                "payload_bytes": len(serialized),
            }
        )

    accepted = await repo.insert_diagnostics(rows)
    logger.info(
        "[MobileDiagnostics] accepted %d envelope(s) from %s... (%s)",
        accepted,
        current_user.user_id,
        ", ".join(sorted({row["diagnostic_type"] for row in rows})),
    )
    return DiagnosticsIngestResponse(accepted=accepted)


# ---------------------------------------------------------------------------
# Push device registration (APNs key boundary)
# ---------------------------------------------------------------------------

class PushDeviceRegistration(BaseModel):
    device_id: str = Field(..., min_length=8, max_length=128)
    apns_token: str = Field(..., min_length=16, max_length=512, pattern=r"^[0-9a-fA-F]+$")
    environment: str = Field(..., pattern=r"^(sandbox|production)$")
    app_version: Optional[str] = Field(None, max_length=64)


class PushDeviceAck(BaseModel):
    device_id: str


@router.post("/push/devices", response_model=PushDeviceAck)
@rate_limit(category="mobile_diagnostics")
async def register_push_device(
    request: Request,
    payload: PushDeviceRegistration = Body(...),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: MobileOpsRepository = Depends(get_mobile_ops_repository),
) -> PushDeviceAck:
    """Record (or replace) one install's APNs token. Registration is
    authenticated and replaceable: the same device_id upserts, and a device
    changing riders re-binds to the new wallet."""
    await repo.upsert_push_device(
        device_id=payload.device_id,
        wallet=current_user.wallet,
        apns_token=payload.apns_token.lower(),
        environment=payload.environment,
        app_version=payload.app_version,
    )
    return PushDeviceAck(device_id=payload.device_id)


@router.delete("/push/devices/{device_id}")
@rate_limit(category="mobile_diagnostics")
async def unregister_push_device(
    request: Request,
    device_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: MobileOpsRepository = Depends(get_mobile_ops_repository),
) -> dict[str, bool]:
    """Sign-out path: drop this install's registration. Wallet-guarded —
    a rider can only remove their own device rows."""
    removed = await repo.delete_push_device(
        device_id=device_id, wallet=current_user.wallet
    )
    return {"removed": removed}
