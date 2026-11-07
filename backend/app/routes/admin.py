import logging
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional, Tuple
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

from ..compliance_repository import ComplianceRepository
from ..dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_repository,
    get_ride_repository,
)
from ..repositories import (
    DatabaseRepository,
    RideEconomicRepository,
    RideRepository,
    create_ride_economic_repository,
)
from ..middleware.rate_limiter import rate_limit
from ..services.backfill_service import enqueue_vault_backfill_job
from ..services.emergency_controls import EmergencyControls
from ..services.epoch_processor import get_epoch_processor
from ..services.file_storage import create_file_storage_service
from ..services.ride_chain_accounts import (
    ChainAccountMismatchError,
    ChainAccountUnavailableError,
)
from ..services.ride_economic_review import (
    FinalizedRideEconomicEvidenceCollector,
    RideEconomicReviewResolutionService,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class ControlUpdate(BaseModel):
    enabled: bool
    reason: Optional[str] = None


class AdminResponse(BaseModel):
    success: bool
    message: str


class EpochProcessResponse(BaseModel):
    transitioned: bool
    processed: int


class EpochStatusResponse(BaseModel):
    current_epoch: int
    stored_epoch: int
    epoch_needs_transition: bool
    pending_distributions: int
    pending_dung_total: str
    recently_completed: int
    blocked_distributions: int = 0
    blocked_reasons: list[str] = Field(default_factory=list)
    oldest_blocked_at: Optional[str] = None
    preconditions_pending: int = 0
    reconciliation_pending: int = 0
    review_required: int = 0
    settlement_healthy: bool = True


class RideMediaCleanupResponse(BaseModel):
    scanned: int
    deleted_rows: int
    deleted_objects: int
    failed: int


class RideEconomicReviewResolutionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    request_id: UUID
    review_version: int = Field(gt=0)
    outcome: Literal["reconcile", "resume", "reject"]
    selected_checkpoint: Optional[
        Literal[
            "planned",
            "attestation_confirmed",
            "completions_confirmed",
            "cal_confirmed",
        ]
    ]
    reason: str = Field(min_length=1, max_length=2000)
    liability_disposition: Optional[str] = Field(default=None, max_length=2000)
    effects_disposition: Optional[str] = Field(default=None, max_length=2000)

    @model_validator(mode="after")
    def validate_outcome_fields(self):
        if self.outcome == "resume" and self.selected_checkpoint is None:
            raise ValueError("resume requires selected_checkpoint")
        if self.outcome != "resume" and self.selected_checkpoint is not None:
            raise ValueError("selected_checkpoint is only valid for resume")
        if self.outcome == "reject" and (
            not (self.liability_disposition or "").strip()
            or not (self.effects_disposition or "").strip()
        ):
            raise ValueError("reject requires liability and effects dispositions")
        return self


async def require_admin(
    current_user: AuthenticatedUser = Depends(get_current_user),
) -> Tuple[UUID, str]:
    repo = ComplianceRepository()
    role = await repo.get_admin_role(UUID(current_user.user_id))
    if not role:
        raise HTTPException(status_code=403, detail="Admin access required")
    return UUID(current_user.user_id), role


def get_ride_economic_review_repository() -> RideEconomicRepository:
    return create_ride_economic_repository()


def get_ride_economic_review_service() -> RideEconomicReviewResolutionService:
    repository = create_ride_economic_repository()
    return RideEconomicReviewResolutionService(
        repository=repository,
        evidence_collector=FinalizedRideEconomicEvidenceCollector(),
    )


@router.get("/check")
@rate_limit(category="general")
async def check_admin_status(
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
):
    """Check if current user has admin access without treating non-admins as request failures."""
    role = await ComplianceRepository().get_admin_role(UUID(current_user.user_id))
    return {"isAdmin": bool(role), "role": role}


@router.get("/ride-economics/{ride_id}/review")
@rate_limit(category="general")
async def inspect_ride_economic_review(
    request: Request,
    ride_id: UUID,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repository: RideEconomicRepository = Depends(
        get_ride_economic_review_repository
    ),
):
    review = await repository.get_review(ride_id)
    if review is None:
        raise HTTPException(status_code=404, detail="Ride economic review not found")
    return review


@router.post("/ride-economics/{ride_id}/review/resolve")
@rate_limit(category="general")
async def resolve_ride_economic_review(
    request: Request,
    ride_id: UUID,
    resolution: RideEconomicReviewResolutionRequest,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    service: RideEconomicReviewResolutionService = Depends(
        get_ride_economic_review_service
    ),
):
    admin_id, _role = admin_ctx
    try:
        return await service.resolve(
            ride_id=ride_id,
            expected_review_version=resolution.review_version,
            request_id=resolution.request_id,
            actor_id=admin_id,
            outcome=resolution.outcome,
            selected_checkpoint=resolution.selected_checkpoint,
            reason=resolution.reason,
            liability_disposition=resolution.liability_disposition,
            effects_disposition=resolution.effects_disposition,
        )
    except ChainAccountUnavailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except (ChainAccountMismatchError, RuntimeError, ValueError) as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/ride-media/cleanup", response_model=RideMediaCleanupResponse)
@rate_limit(category="general")
async def cleanup_stale_ride_media(
    request: Request,
    older_than_hours: int = Query(default=24, ge=1, le=24 * 30),
    limit: int = Query(default=100, ge=1, le=500),
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> RideMediaCleanupResponse:
    """Delete stale rows only after both photo lifecycle objects are removed."""
    older_than = (datetime.now(timezone.utc) - timedelta(hours=older_than_hours)).isoformat()
    rows = await ride_repo.list_stale_ride_media_uploads(older_than=older_than, limit=limit)
    storage = create_file_storage_service()
    deleted_rows = 0
    deleted_objects = 0
    failed = 0

    for row in rows:
        media_id = str(row.get("id") or "")
        storage_path = row.get("storage_path")
        try:
            if isinstance(storage_path, str) and storage_path.strip():
                deleted_objects += await storage.delete_photo_files(storage_path)
            if media_id:
                await ride_repo.delete_ride_media(media_id)
                deleted_rows += 1
        except Exception:
            failed += 1
            logger.warning(
                "Failed stale ride media cleanup media_id=%s storage_path=%s",
                media_id,
                "[redacted]",
                exc_info=True,
            )

    return RideMediaCleanupResponse(
        scanned=len(rows),
        deleted_rows=deleted_rows,
        deleted_objects=deleted_objects,
        failed=failed,
    )


@router.get("/controls")
@rate_limit(category="general")
async def get_all_controls(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """Get all system controls."""
    repo = ComplianceRepository()
    controls = await repo.list_system_controls()

    return {
        "controls": [
            {
                "key": row.get("key"),
                "value": row.get("value"),
                "updated_at": row.get("updated_at"),
                "updated_by": str(row.get("updated_by")) if row.get("updated_by") else None,
            }
            for row in controls
        ]
    }


@router.put("/controls/{control_key}")
@rate_limit(category="general")
async def update_control(
    control_key: str,
    update: ControlUpdate,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """Update a system control (emergency pause/resume)."""
    admin_id, _role = admin_ctx
    controls_service = EmergencyControls()
    compliance = ComplianceRepository()

    valid_controls = [
        "staking_enabled",
        "minting_enabled",
        "uploads_enabled",
        "withdrawals_enabled",
        "maintenance_mode",
    ]

    if control_key not in valid_controls:
        raise HTTPException(status_code=400, detail=f"Invalid control key. Valid: {valid_controls}")

    await controls_service.set_control(control_key, enabled=update.enabled, reason=update.reason, admin_id=admin_id)

    await compliance.log_audit_event(
        action=f"system_control_{'enabled' if update.enabled else 'disabled'}",
        user_id=admin_id,
        target_type="system_control",
        metadata={
            "control": control_key,
            "enabled": update.enabled,
            "reason": update.reason,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    action = "enabled" if update.enabled else "disabled"
    return AdminResponse(success=True, message=f"{control_key} has been {action}")


@router.post("/emergency/pause-all")
@rate_limit(category="general")
async def emergency_pause_all(
    request: Request,
    reason: str,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """Emergency pause ALL operations."""
    admin_id, _role = admin_ctx
    controls_service = EmergencyControls()
    compliance = ComplianceRepository()

    for control in ["staking_enabled", "minting_enabled", "uploads_enabled", "withdrawals_enabled"]:
        await controls_service.set_control(control, enabled=False, reason=reason, admin_id=admin_id)

    await controls_service.set_control("maintenance_mode", enabled=True, reason=reason, admin_id=admin_id)

    await compliance.log_audit_event(
        action="emergency_pause_all",
        user_id=admin_id,
        metadata={"reason": reason},
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return AdminResponse(success=True, message=f"EMERGENCY PAUSE ACTIVATED: {reason}")


@router.post("/emergency/resume-all")
@rate_limit(category="general")
async def emergency_resume_all(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
):
    """Resume all operations after emergency pause."""
    admin_id, role = admin_ctx
    if role != "super_admin":
        raise HTTPException(status_code=403, detail="Super admin required to resume after emergency")

    controls_service = EmergencyControls()
    compliance = ComplianceRepository()

    for control in ["staking_enabled", "minting_enabled", "uploads_enabled", "withdrawals_enabled"]:
        await controls_service.set_control(control, enabled=True, reason=None, admin_id=admin_id)

    await controls_service.set_control("maintenance_mode", enabled=False, reason=None, admin_id=admin_id)

    await compliance.log_audit_event(
        action="emergency_resume_all",
        user_id=admin_id,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return AdminResponse(success=True, message="All operations resumed")


@router.get("/epoch/status", response_model=EpochStatusResponse)
@rate_limit(category="general")
async def get_epoch_status(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get current epoch status including pending distributions.

    Returns epoch state, whether a transition is needed, and distribution counts.
    """
    processor = get_epoch_processor(repo.client)
    settlement_clock = await processor._load_settlement_clock()
    current_epoch = settlement_clock.week_at(
        int(datetime.now(timezone.utc).timestamp())
    )
    stored_epoch = await processor.get_stored_epoch()

    status = await processor._settlement_queue.status()

    return EpochStatusResponse(
        current_epoch=current_epoch,
        stored_epoch=stored_epoch,
        epoch_needs_transition=current_epoch > stored_epoch,
        pending_distributions=status["pending"],
        pending_dung_total=status["pending_dung"],
        recently_completed=status["confirmed"],
        blocked_distributions=status["blocked"],
        blocked_reasons=status["blocked_reasons"],
        oldest_blocked_at=status["oldest_blocked_at"],
        preconditions_pending=status["preconditions_pending"],
        reconciliation_pending=status["reconciliation_pending"],
        review_required=status["review_required"],
        settlement_healthy=status["healthy"],
    )


class BackfillRequest(BaseModel):
    priority: Optional[int] = 0


class BackfillResponse(BaseModel):
    vault_id: int
    vault_name: str
    backfill_status: str
    message: str


class BackfillStatusResponse(BaseModel):
    vault_id: int
    vault_name: str
    backfill_status: str
    backfill_completions_found: Optional[int]
    backfill_error: Optional[str]
    backfill_started_at: Optional[str]
    backfill_completed_at: Optional[str]


@router.post("/vaults/{vault_id}/backfill", response_model=BackfillResponse)
@rate_limit(category="general")
async def trigger_vault_backfill(
    vault_id: int,
    request: Request,
    body: Optional[BackfillRequest] = None,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Manually trigger backfill for a vault.

    This finds all historical rides matching the vault's climb signature
    and populates the leaderboard and completion records.

    Use this when:
    - A vault was created before backfill was implemented
    - A backfill job failed and needs to be retried
    - You want to force a re-backfill with higher priority

    The backfill runs asynchronously in the background.
    """
    from ..generated_program_version import PROGRAM_VERSION_FAMILY

    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy detector backfill is disabled for V4-B; "
                "canon traversal is the sole economic authority."
            ),
        )
    admin_id, _role = admin_ctx

    # Get vault details
    vault_result = repo.client.from_("indexed_vaults") \
        .select("id, name, signature_hex, backfill_status") \
        .eq("id", vault_id) \
        .execute()

    if not vault_result.data:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")

    vault = vault_result.data[0]

    # Queue backfill task
    priority = body.priority if body else 0
    await enqueue_vault_backfill_job(
        supabase_client=repo.client,
        vault_id=vault_id,
        vault_signature=vault["signature_hex"],
        priority=priority,
    )

    # Audit log
    compliance = ComplianceRepository()
    await compliance.log_audit_event(
        action="vault_backfill_triggered",
        user_id=admin_id,
        target_type="vault",
        metadata={
            "vault_id": vault_id,
            "vault_name": vault["name"],
            "priority": priority,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return BackfillResponse(
        vault_id=vault_id,
        vault_name=vault["name"],
        backfill_status="queued",
        message=f"Backfill job queued for vault '{vault['name']}'"
    )


@router.get("/vaults/{vault_id}/backfill/status", response_model=BackfillStatusResponse)
@rate_limit(category="general")
async def get_vault_backfill_status(
    vault_id: int,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get backfill status for a vault.

    Returns current backfill state including:
    - Status (pending, in_progress, completed, failed)
    - Number of completions found
    - Any error message
    - Timestamps
    """
    vault_result = repo.client.from_("indexed_vaults") \
        .select("id, name, backfill_status, backfill_completions_found, backfill_error, backfill_started_at, backfill_completed_at") \
        .eq("id", vault_id) \
        .execute()

    if not vault_result.data:
        raise HTTPException(status_code=404, detail=f"Vault {vault_id} not found")

    vault = vault_result.data[0]
    return BackfillStatusResponse(
        vault_id=vault["id"],
        vault_name=vault["name"],
        backfill_status=vault.get("backfill_status", "unknown"),
        backfill_completions_found=vault.get("backfill_completions_found"),
        backfill_error=vault.get("backfill_error"),
        backfill_started_at=vault.get("backfill_started_at"),
        backfill_completed_at=vault.get("backfill_completed_at"),
    )


@router.post("/vaults/backfill-all")
@rate_limit(category="general")
async def trigger_all_pending_backfills(
    request: Request,
    force: bool = False,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Trigger backfill for all vaults that haven't been backfilled yet.

    By default, queues backfill jobs for vaults where:
    - backfill_status is NULL or 'pending'
    - backfill_status is 'failed' (for retry)

    With force=true, also re-backfills completed vaults.
    Use force=true when patterns have been updated with new signatures.

    Jobs are queued with default priority.
    """
    from ..generated_program_version import PROGRAM_VERSION_FAMILY

    if PROGRAM_VERSION_FAMILY == "V4-B":
        raise HTTPException(
            status_code=status.HTTP_410_GONE,
            detail=(
                "Legacy detector backfill is disabled for V4-B; "
                "canon traversal is the sole economic authority."
            ),
        )
    admin_id, _role = admin_ctx

    # Find vaults needing backfill
    if force:
        # Re-backfill ALL vaults (useful after pattern signature updates)
        vaults_result = repo.client.from_("indexed_vaults") \
            .select("id, name, signature_hex, backfill_status") \
            .execute()
    else:
        vaults_result = repo.client.from_("indexed_vaults") \
            .select("id, name, signature_hex, backfill_status") \
            .or_("backfill_status.is.null,backfill_status.eq.pending,backfill_status.eq.failed") \
            .execute()

    vaults = vaults_result.data or []

    # Queue backfill for each
    queued = 0
    for vault in vaults:
        try:
            if force:
                from ..tasks import backfill_vault_leaderboard

                # Force mode intentionally bypasses the idempotent queue so completed
                # vaults can be replayed again after matcher/signature changes.
                backfill_vault_leaderboard.delay(
                    vault_id=vault["id"],
                    vault_signature=vault["signature_hex"],
                )
            else:
                await enqueue_vault_backfill_job(
                    supabase_client=repo.client,
                    vault_id=vault["id"],
                    vault_signature=vault["signature_hex"],
                )
            queued += 1
        except Exception as e:
            logger.warning(f"Failed to queue backfill for vault {vault['id']}: {e}")

    # Audit log
    compliance = ComplianceRepository()
    await compliance.log_audit_event(
        action="vault_backfill_all_triggered",
        user_id=admin_id,
        metadata={
            "total_vaults": len(vaults),
            "queued": queued,
            "force": force,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return {
        "message": f"Queued {queued} vault backfill jobs" + (" (force re-backfill)" if force else ""),
        "total_vaults": len(vaults),
        "queued": queued,
        "force": force,
    }


class SignatureBackfillResponse(BaseModel):
    """Response for signature backfill operation."""
    message: str
    task_id: str
    dry_run: bool
    limit: int


@router.post("/patterns/backfill-signatures", response_model=SignatureBackfillResponse)
@rate_limit(category="general")
async def trigger_signature_backfill(
    request: Request,
    limit: int = 50,
    dry_run: bool = False,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Backfill missing signatures for climb patterns.

    This task finds patterns_climb records without signature_hex and
    regenerates them from activity_tile_samples data.

    Background:
    - Patterns created before Dec 23, 2025 don't have signatures
    - Without signatures, they can't be matched to vaults during backfill
    - This task regenerates signatures using the stored elevation data

    Args:
        limit: Max patterns to process (default 50)
        dry_run: If true, logs what would happen without updating

    Returns:
        Task ID for tracking progress in worker logs
    """
    from ..tasks import backfill_pattern_signatures

    admin_id, _role = admin_ctx
    compliance = ComplianceRepository()

    # Get count of patterns needing signatures
    count_result = repo.client.table("patterns_climb") \
        .select("id", count="exact") \
        .is_("signature_hex", "null") \
        .execute()
    total_missing = count_result.count or 0

    # Queue the task
    task = backfill_pattern_signatures.delay(limit=limit, dry_run=dry_run)

    # Audit log
    await compliance.log_audit_event(
        action="signature_backfill_triggered",
        user_id=admin_id,
        metadata={
            "task_id": task.id,
            "limit": limit,
            "dry_run": dry_run,
            "total_missing_signatures": total_missing,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return SignatureBackfillResponse(
        message=f"Queued signature backfill for up to {limit} patterns ({total_missing} total missing)",
        task_id=task.id,
        dry_run=dry_run,
        limit=limit,
    )


@router.get("/patterns/signature-status")
@rate_limit(category="general")
async def get_signature_status(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get status of pattern signatures.

    Returns counts of patterns with and without signatures,
    useful for monitoring backfill progress.
    """
    # Count patterns with signatures
    with_sig = repo.client.table("patterns_climb") \
        .select("id", count="exact") \
        .not_.is_("signature_hex", "null") \
        .execute()

    # Count patterns without signatures
    without_sig = repo.client.table("patterns_climb") \
        .select("id", count="exact") \
        .is_("signature_hex", "null") \
        .execute()

    return {
        "patterns_with_signature": with_sig.count or 0,
        "patterns_without_signature": without_sig.count or 0,
        "total_patterns": (with_sig.count or 0) + (without_sig.count or 0),
        "completion_pct": round(
            (with_sig.count or 0) / max((with_sig.count or 0) + (without_sig.count or 0), 1) * 100,
            1
        ),
    }


@router.post("/epoch/process", response_model=EpochProcessResponse)
@rate_limit(category="general")
async def process_epoch_distributions(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Manually trigger epoch transition checks and process pending distributions.

    This is the same operation that runs automatically in the background,
    but can be triggered manually by admins for immediate processing.

    Flow:
    1. Reconcile and recover existing durable settlement jobs.
    2. Materialize the next complete VaultCounter week when the cursor is clear.
    3. Atomically claim and submit ready jobs, then reconcile chain evidence.

    Use GET /admin/epoch/status to check state before triggering.
    """
    admin_id, _role = admin_ctx
    processor = get_epoch_processor(repo.client)
    compliance = ComplianceRepository()

    transitioned, processed = await processor.process_settlement_cycle()

    # Audit log
    await compliance.log_audit_event(
        action="epoch_process_triggered",
        user_id=admin_id,
        metadata={
            "transitioned": transitioned,
            "distributions_processed": processed,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return EpochProcessResponse(transitioned=transitioned, processed=processed)


# =============================================================================
# LEADERBOARD SYNC ENDPOINTS
# =============================================================================


class LeaderboardSyncStatusResponse(BaseModel):
    vault_id: int
    vault_signature: str
    in_sync: bool
    db_entries: int
    onchain_entries: int
    differences: list
    last_sync_at: Optional[str]
    sync_status: Optional[str]


class LeaderboardSyncResponse(BaseModel):
    vault_id: int
    status: str
    entries_synced: int
    tx_signature: Optional[str]
    error: Optional[str]


class LeaderboardSyncAllResponse(BaseModel):
    total: int
    synced: int
    mismatches: int
    failed: int
    skipped: int


@router.get("/vaults/{vault_id}/leaderboard/sync-status", response_model=LeaderboardSyncStatusResponse)
@rate_limit(category="general")
async def get_leaderboard_sync_status(
    vault_id: int,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Compare DB vs on-chain leaderboard state for a vault.

    Returns detailed comparison showing:
    - Whether states are in sync
    - Number of entries in each
    - Specific differences
    - Last sync timestamp

    Use this to diagnose leaderboard projection mismatches. Settlement
    distribution reads the on-chain PDA directly and does not depend on this
    cache agreeing first.
    """
    from ..services.leaderboard_sync_service import LeaderboardSyncService

    sync_service = LeaderboardSyncService(repo.client)
    verification = await sync_service.verify_sync(vault_id)

    if "error" in verification:
        raise HTTPException(status_code=404, detail=verification["error"])

    # Get sync tracking info from indexed_vaults
    vault_resp = repo.client.from_("indexed_vaults") \
        .select("last_onchain_sync_at, onchain_sync_status") \
        .eq("id", vault_id) \
        .limit(1) \
        .execute()

    last_sync_at = None
    sync_status = None
    if vault_resp.data:
        last_sync_at = vault_resp.data[0].get("last_onchain_sync_at")
        sync_status = vault_resp.data[0].get("onchain_sync_status")

    return LeaderboardSyncStatusResponse(
        vault_id=vault_id,
        vault_signature=verification["vault_signature"],
        in_sync=verification["in_sync"],
        db_entries=verification["db_entries"],
        onchain_entries=verification["onchain_entries"],
        differences=verification["differences"],
        last_sync_at=last_sync_at,
        sync_status=sync_status,
    )


@router.post("/vaults/{vault_id}/leaderboard/sync", response_model=LeaderboardSyncResponse)
@rate_limit(category="general")
async def trigger_leaderboard_sync(
    vault_id: int,
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Manually trigger a leaderboard-projection verification for a vault.

    Compares DB cache (``vault_leaderboards``) against the authoritative
    on-chain ``VaultLeaderboard`` PDA and:
    1. Logs any differences
    2. Updates sync status in ``indexed_vaults``
    3. Records the check into ``leaderboard_sync_log``

    Note (BACKEND_TRUTHS §10.1 / §10.3): this endpoint reports drift; it
    does NOT write DB state onto chain. On-chain is authoritative — repair
    drift by re-indexing from the chain, not by pushing DB state.
    """
    from ..services.leaderboard_sync_service import LeaderboardSyncService

    admin_id, _role = admin_ctx
    sync_service = LeaderboardSyncService(repo.client)

    result = await sync_service.sync_vault_leaderboard(
        vault_id=vault_id,
        sync_type="manual",
        triggered_by=f"admin:{admin_id}",
    )

    # Audit log
    compliance = ComplianceRepository()
    await compliance.log_audit_event(
        action="leaderboard_sync_triggered",
        user_id=admin_id,
        target_type="vault",
        metadata={
            "vault_id": vault_id,
            "status": result.status,
            "entries_synced": result.entries_synced,
            "error": result.error,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return LeaderboardSyncResponse(
        vault_id=result.vault_id,
        status=result.status,
        entries_synced=result.entries_synced,
        tx_signature=result.tx_signature,
        error=result.error,
    )


@router.post("/leaderboards/sync-all", response_model=LeaderboardSyncAllResponse)
@rate_limit(category="general")
async def trigger_all_leaderboard_sync(
    request: Request,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Verify all active vault leaderboard projections.

    This is an observability-only check. It compares read-layer cache rows
    against on-chain VaultLeaderboard PDAs and records drift; it does not
    write DB state to chain and is not part of distribution execution.

    Returns summary of:
    - Total vaults processed
    - How many were already in sync
    - How many had mismatches
    - How many failed
    """
    from ..services.leaderboard_sync_service import LeaderboardSyncService

    admin_id, _role = admin_ctx
    sync_service = LeaderboardSyncService(repo.client)

    results = await sync_service.sync_all_active_vaults()

    response = LeaderboardSyncAllResponse(
        total=len(results),
        synced=sum(1 for r in results if r.status == "synced"),
        mismatches=sum(1 for r in results if r.status == "mismatch_detected"),
        failed=sum(1 for r in results if r.status == "failed"),
        skipped=sum(1 for r in results if r.status == "skipped"),
    )

    # Audit log
    compliance = ComplianceRepository()
    await compliance.log_audit_event(
        action="leaderboard_sync_all_triggered",
        user_id=admin_id,
        metadata={
            "total": response.total,
            "synced": response.synced,
            "mismatches": response.mismatches,
            "failed": response.failed,
        },
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent"),
    )

    return response


@router.get("/leaderboards/sync-log")
@rate_limit(category="general")
async def get_leaderboard_sync_log(
    request: Request,
    vault_id: Optional[int] = None,
    status: Optional[str] = None,
    limit: int = 50,
    admin_ctx: Tuple[UUID, str] = Depends(require_admin),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get leaderboard sync log entries.

    Optional filters:
    - vault_id: Filter by specific vault
    - status: Filter by sync status (synced, failed, mismatch_detected, skipped)
    - limit: Max entries to return (default 50)

    Returns recent sync operations for debugging sync issues.
    """
    query = repo.client.from_("leaderboard_sync_log") \
        .select("*") \
        .order("created_at", desc=True) \
        .limit(limit)

    if vault_id is not None:
        query = query.eq("vault_id", vault_id)

    if status:
        query = query.eq("status", status)

    result = query.execute()

    return {
        "entries": result.data or [],
        "count": len(result.data or []),
    }
