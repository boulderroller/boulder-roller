from ..services.subject_states import ride_subject_states
from ..services.training_eligibility import is_training_eligible
from ..repositories.climb_effort import ClimbEffortRepository
from ..services.climb_effort_reads import pattern_power
from ..client_contracts import ClimbPatternPower

import asyncio
import base64
from datetime import datetime, timezone
import inspect
import json
import logging
import posixpath
import time
from typing import Any, Literal, Optional, Tuple, Union
from uuid import UUID
import uuid as uuid_module

import jwt
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from ..config import is_public_environment, load_auth_settings
from ..dependencies import AuthenticatedUser, get_current_user, get_optional_current_user, get_repository, get_ride_repository, get_user_repository
from ..middleware.rate_limiter import rate_limit
from ..metrics import KPI_RIDE_UPLOADS
from ..repositories import (
    DatabaseRepository,
    RideRepository,
    UserRepository,
    is_authoritative_completion,
    is_authoritative_tribute,
)
from ..security import verify_access_token
from ..services.privacy_logging import scrub_log_text
from ..utils.postgrest_paging import PageCursor, order_by
from ..services.file_storage import (
    create_file_storage_service,
    StorageUnavailableError,
    FileTooLargeError,
    FileNotFoundError as StorageFileNotFoundError,
)
from ..services.photo_metadata import InvalidPhotoError
from ..ride_media_contracts import (
    serialize_ride_media,
    serialize_ride_media_list,
)
from ..services.cal_tribute_policy import (
    CAL_TRIBUTE_POLICY_VERSION,
)
from ..services.ride_ingest import RideIngestJob, enqueue_ride_ingest
from ..services.ride_effort_policy import (
    PRE_ECONOMY_REVIEW_REASON,
    is_pre_economy_activity,
)
from ..services.ride_provenance_policy import build_ride_provenance_diagnostics
from ..services.canon_traversal import authoritative_canon_climb_id
from ..services.default_ride_title import place_label_for_ride
from ..services.record_board_projection import project_competition_entries
from ..services.ride_list_shape import build_ride_list_shape
from ..services.elevation_correction import decode_correction_profile
from ..services.privacy_resolver import (
    VisibilityDecision,
    normalize_visibility,
    resolve_ride_visibility,
)
from ..services.ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    project_route_points,
    strip_hidden_point_details,
)
from ..feed_contracts import build_route_preview
from ..client_contracts import (
    RideEffortEconomy,
    RideInputQuality,
    RideClimbEarning,
    RideEarnings,
    RideProcessingFailure,
    RideProgression,
    RideStatusMetrics,
    RideStatusResponse,
    TruthSource,
)
from ..schemas import (
    ElevationCorrectionInfo,
    RideCalItemization,
    RideCalItemizationClimb,
    RideRecord,
    RideMedia,
    RideMediaCompleteRequest,
    RideMediaInitRequest,
    RideMediaInitResponse,
    RideMediaReorderRequest,
    RideMediaUpdateRequest,
    PrivacyState,
    RideUploadRequest,
    RideUploadResponse,
    RideUpdateRequest,
    UploadInitRequest,
    UploadInitResponse,
    UploadCompleteRequest,
    UploadCompleteResponse,
    UploadAbortRequest,
    UploadAbortResponse,
)

router = APIRouter()
logger = logging.getLogger(__name__)
_auth_settings = load_auth_settings()


def _reject_public_force_upload(force: bool) -> None:
    if force and is_public_environment():
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="force upload is only available in non-public environments",
        )

RETRYABLE_UPLOAD_DUPLICATE_STATUSES = {"failed", "uploading"}
IN_PROGRESS_UPLOAD_DUPLICATE_STATUSES = {"pending", "processing"}
READY_UPLOAD_DUPLICATE_STATUSES = {
    "metrics_ready",
    "enriched",
    "completed",
    "patterns_detected",
}
ALLOWED_RIDE_MEDIA_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}
MAX_RIDE_MEDIA_PER_RIDE = 6
CLIMB_EARNING_READY_STATUSES = {"enriched", "completed", "under_review"}
UPLOAD_COMPLETE_HASH_WARN_MS = 1500


def _upload_import_diagnostics(
    *,
    preliminary_ride_hash: Optional[str],
    parser_version: Optional[int],
    base: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    return build_ride_provenance_diagnostics(
        preliminary_ride_hash=preliminary_ride_hash,
        parser_version=parser_version,
        base=base,
    )


def _normalize_media_mime_type(value: str) -> str:
    normalized = (value or "").split(";", 1)[0].strip().lower()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def _media_extension(mime_type: str, file_name: Optional[str]) -> str:
    normalized = _normalize_media_mime_type(mime_type)
    ext = ALLOWED_RIDE_MEDIA_MIME_TYPES.get(normalized)
    if ext:
        return ext
    if file_name and "." in file_name:
        candidate = file_name.rsplit(".", 1)[-1].strip().lower()
        if candidate in {"jpg", "jpeg", "png", "webp", "heic", "heif"}:
            return "jpg" if candidate == "jpeg" else candidate
    return "jpg"


async def resolve_authorization(
    authorization: Optional[str],
    repo: DatabaseRepository,
) -> Tuple[str, str]:
    """
    Resolve bearer token to (wallet, user_id).
    Used by mint routes for token operations.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid authorization header",
        )
    token = authorization.split(" ", 1)[1].strip()
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing bearer token",
        )
    try:
        claims = verify_access_token(token, _auth_settings.access_token_secret, _auth_settings.audience)
    except jwt.PyJWTError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        ) from exc

    wallet = claims.get("sub")
    if not wallet:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid access token",
        )

    user_id = await repo.get_user_id(wallet)
    if not user_id:
        user_id = await repo.create_user(wallet)

    return wallet, user_id


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _derive_attestation_status(data: dict[str, Any]) -> str:
    processing_status = data.get("processing_status") or "pending"
    if processing_status == "under_review" or data.get("canonical_match") is False:
        return "under_review"
    if data.get("ride_attestation_pda"):
        return "attested"
    if processing_status == "failed":
        return "failed"
    if processing_status in ("metrics_ready", "enriched", "completed"):
        return "provisional"
    return "pending"


def _derive_processing_stage(data: dict[str, Any]) -> str:
    status = str(data.get("processing_status") or "pending")
    if status == "pending":
        return "queued"
    if status in {
        "uploading",
        "processing",
        "metrics_ready",
        "enriched",
        "under_review",
        "completed",
        "failed",
    }:
        return status
    return "unknown"


def _error_looks_retryable(message: Optional[str]) -> bool:
    if not message:
        return False
    normalized = message.lower()
    retry_markers = (
        "retry",
        "temporarily",
        "timeout",
        "timed out",
        "queue",
        "nats",
        "storage unavailable",
        "connection",
    )
    return any(marker in normalized for marker in retry_markers)


def _can_retry_processing(data: dict[str, Any]) -> bool:
    status = str(data.get("processing_status") or "pending")
    if status not in {"pending", "failed"}:
        return False
    return bool(data.get("raw_file_path"))


def _upload_duplicate_detail(existing: dict[str, Any]) -> dict[str, Any]:
    existing_status = str(existing.get("processing_status") or "unknown")
    if existing_status in IN_PROGRESS_UPLOAD_DUPLICATE_STATUSES:
        message = "This file is already being processed."
    elif existing_status == "under_review":
        message = "This ride is already uploaded and needs review."
    elif existing_status in READY_UPLOAD_DUPLICATE_STATUSES:
        message = "This file has already been uploaded."
    else:
        message = "This file already has an upload record."

    return {
        "error": "duplicate_file",
        "message": message,
        "existing_ride_id": existing["id"],
        "existing_status": existing_status,
        "uploaded_at": existing.get("uploaded_at"),
    }


async def _find_blocking_upload_duplicate(
    ride_repo: RideRepository,
    user_id: str,
    file_hash: str,
    *,
    context: str,
) -> Optional[dict[str, Any]]:
    if hasattr(type(ride_repo), "find_rides_by_hash"):
        candidates = await ride_repo.find_rides_by_hash(user_id, file_hash)
    else:
        existing = await ride_repo.find_ride_by_hash(user_id, file_hash)
        candidates = [existing] if existing else []

    if not candidates:
        return None

    blocking = next(
        (
            candidate
            for candidate in candidates
            if str(candidate.get("processing_status") or "unknown")
            not in RETRYABLE_UPLOAD_DUPLICATE_STATUSES
        ),
        None,
    )
    if blocking:
        existing_status = str(blocking.get("processing_status") or "unknown")
        existing_id = str(blocking.get("id") or "")
        logger.info(
            f"[{context}] Duplicate detected for user {user_id}: "
            f"file_hash={file_hash[:16]}..., existing_ride={existing_id}, "
            f"existing_status={existing_status}"
        )
        return blocking

    retryable = candidates[0]
    existing_status = str(retryable.get("processing_status") or "unknown")
    existing_id = str(retryable.get("id") or "")

    logger.info(
        f"[{context}] Ignoring retryable duplicate for user {user_id}: "
        f"file_hash={file_hash[:16]}..., existing_ride={existing_id}, "
        f"existing_status={existing_status}"
    )
    if existing_status == "uploading" and existing_id:
        try:
            await ride_repo.update_ride_status(
                UUID(existing_id),
                "failed",
                error_message="Superseded by retry before upload completed",
            )
        except Exception as exc:
            logger.warning(
                f"[{context}] Failed to mark stranded upload {existing_id} as failed: {exc}"
            )
    return None


def _derive_processing_failure(data: dict[str, Any]) -> Optional[RideProcessingFailure]:
    status = str(data.get("processing_status") or "pending")
    phase_errors = (
        ("metrics", data.get("phase1_error")),
        ("enrichment", data.get("phase2_error")),
        ("settlement", data.get("phase3_error")),
    )
    for phase, message in phase_errors:
        if message:
            return RideProcessingFailure(
                phase=phase,
                message=str(message),
                retryable=_can_retry_processing(data) or _error_looks_retryable(str(message)),
            )

    message = data.get("error_message")
    if not message:
        return None

    phase = "unknown"
    normalized = str(message).lower()
    if status == "pending" or "queue" in normalized or "nats" in normalized:
        phase = "queue"
    elif (
        "upload aborted" in normalized
        or "upload record" in normalized
        or "file not found" in normalized
        or "storage" in normalized
    ):
        phase = "upload"
    elif status == "failed":
        phase = "processing"

    return RideProcessingFailure(
        phase=phase,
        message=str(message),
        retryable=_can_retry_processing(data) or _error_looks_retryable(str(message)),
    )


def _dedupe_strings(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        if value is None:
            continue
        text = str(value).strip()
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
    return out


def _coverage_value(data: dict[str, Any], key: str) -> Optional[float]:
    value = data.get(key)
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _derive_sensor_data_state(
    power_coverage: Optional[float],
    hr_coverage: Optional[float],
    speed_coverage: Optional[float],
) -> str:
    values = [v for v in (power_coverage, hr_coverage, speed_coverage) if v is not None]
    if not values:
        return "unknown"
    present = [v for v in values if v > 0]
    if not present:
        return "absent"
    if len(present) == len(values) and all(v >= 0.8 for v in present):
        return "present"
    return "partial"


def _derive_input_quality(data: dict[str, Any]) -> RideInputQuality:
    sensor_integrity = data.get("sensor_integrity")
    if not isinstance(sensor_integrity, dict):
        sensor_integrity = {}

    import_diagnostics = data.get("import_diagnostics")
    if not isinstance(import_diagnostics, dict):
        import_diagnostics = {}

    flags = _dedupe_strings(
        list(sensor_integrity.get("flags") or [])
        + list(import_diagnostics.get("flags") or [])
    )
    import_quality_tier = import_diagnostics.get("quality_tier")
    integrity_score = _coverage_value(sensor_integrity, "integrity_score")
    sample_count = _optional_int(
        sensor_integrity.get("sample_count")
        if sensor_integrity
        else import_diagnostics.get("trackpoint_count")
    )

    power_coverage = _coverage_value(sensor_integrity, "power_coverage")
    hr_coverage = _coverage_value(sensor_integrity, "hr_coverage")
    speed_coverage = _coverage_value(sensor_integrity, "speed_coverage")

    degradation_reasons = _dedupe_strings(flags)
    quality_tier = str(import_quality_tier or "").lower()
    severe_flags = [
        flag
        for flag in degradation_reasons
        if "fail" in flag.lower()
        or "implausible" in flag.lower()
        or "teleportation" in flag.lower()
    ]

    quality_status = "unknown"
    if sensor_integrity or import_diagnostics:
        quality_status = "clean"
    if quality_tier in {"degraded", "warn", "warning"} or flags:
        quality_status = "degraded"
    if quality_tier in {"invalid", "failed", "fail"} or severe_flags:
        quality_status = "invalid"
    elif integrity_score is not None:
        if integrity_score < 0.4:
            quality_status = "invalid"
        elif integrity_score < 0.8:
            quality_status = "degraded"

    return RideInputQuality(
        status=quality_status,
        sensor_data_state=_derive_sensor_data_state(
            power_coverage,
            hr_coverage,
            speed_coverage,
        ),
        integrity_score=integrity_score,
        sample_count=sample_count,
        flags=flags,
        degradation_reasons=degradation_reasons,
        gps_coverage=_coverage_value(sensor_integrity, "gps_coverage"),
        elevation_coverage=_coverage_value(sensor_integrity, "elev_coverage"),
        sampling_regularity=_coverage_value(sensor_integrity, "sampling_regularity"),
        max_gap_s=_optional_int(sensor_integrity.get("max_gap_s")),
        power_coverage=power_coverage,
        heart_rate_coverage=hr_coverage,
        speed_coverage=speed_coverage,
        import_quality_tier=str(import_quality_tier) if import_quality_tier else None,
    )


def _optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _optional_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _safe_rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if not isinstance(data, list):
        return []
    return [dict(row) for row in data if isinstance(row, dict)]


def _project_threshold_ride_for_client(
    ride: dict[str, Any],
    projection: dict[str, Any],
) -> dict[str, Any]:
    """Apply one validated child-release state to the immutable parent ride."""
    if ride.get("reward_policy") != "threshold_provisional_hold_v1":
        raise ValueError("Threshold economy state requires a held parent ride")
    if not isinstance(projection, dict):
        raise ValueError("Threshold economy projection is unavailable")
    state = projection.get("state")
    if state not in {"held", "counted", "lapsed", "review", "not_counted"}:
        raise ValueError("Threshold economy projection has an invalid state")

    result = {**ride, "threshold_economy_state": state}
    if state == "counted":
        try:
            economic_tss = float(projection["economic_tss"])
            counted_cal = int(projection["cal_earned"])
            threshold_w = int(projection["threshold_w"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("Counted Threshold release lacks terminal facts") from exc
        if economic_tss < 0 or counted_cal <= 0 or not 50 <= threshold_w <= 500:
            raise ValueError("Counted Threshold release has invalid terminal facts")
        result.update(
            reward_policy="rewardable",
            tss=economic_tss,
            cal_earned=counted_cal,
            rewardable_cal=counted_cal,
            tributable_cal=counted_cal,
            threshold_training_w=threshold_w,
            threshold_training_kind="sealed",
        )
        return result

    result.update(tss=None, cal_earned=None, rewardable_cal=0, tributable_cal=0)
    if state == "review":
        result["reward_policy"] = "manual_review"
    elif state in {"lapsed", "not_counted"}:
        result["reward_policy"] = "not_counted"
    return result


async def _threshold_ride_projections_for_owner(
    repo: Any,
    rides: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    held_ids = [
        str(ride.get("id"))
        for ride in rides
        if ride.get("id")
        and ride.get("reward_policy") == "threshold_provisional_hold_v1"
    ]
    if not held_ids:
        return {}
    try:
        reader = getattr(repo, "get_reward_threshold_ride_projections", None)
        if callable(reader):
            raw = await reader(held_ids)
        else:
            response = await repo._run(
                lambda: repo._client.rpc(
                    "get_reward_threshold_ride_projections",
                    {"p_ride_ids": held_ids},
                ).execute()
            )
            raw = getattr(response, "data", None)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "threshold_economy_authority_unavailable"},
        ) from exc
    if not isinstance(raw, dict) or any(
        not isinstance(raw.get(ride_id), dict) for ride_id in held_ids
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "threshold_economy_authority_unavailable"},
        )
    return {ride_id: dict(raw[ride_id]) for ride_id in held_ids}


async def _project_threshold_training_for_owner(
    repo: Any,
    user_id: str,
    rides: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    from ..services.training_metrics import project_training
    return [project_training(ride, owner=True) for ride in rides]


def _withhold_private_threshold_economy(ride: dict[str, Any]) -> dict[str, Any]:
    from ..services.training_metrics import project_training
    result = project_training(ride, owner=False)
    result["_threshold_economy_withheld"] = True
    result["threshold_training_state"] = None
    result["tss"] = None
    result["total_tss_after"] = None
    result["level_delta"] = None
    result["level_after"] = None
    for field in (
        "dung_minted",
        "cal_earned",
        "estimated_cal",
        "rewardable_cal",
        "tributable_cal",
    ):
        result[field] = None
    if ride.get("reward_policy") == "threshold_provisional_hold_v1":
        for field in (
            "reward_policy",
            "threshold_economy_state",
        ):
            result[field] = None
    return result


def _threshold_economy_visible(ride: dict[str, Any]) -> bool:
    """Admit Threshold CAL/tribute only after the rider projection is counted."""
    if ride.get("_threshold_economy_withheld") is True:
        return False
    state = ride.get("threshold_economy_state")
    if state is not None:
        return state == "counted"
    return ride.get("reward_policy") != "threshold_provisional_hold_v1"


def _withhold_climb_economy(
    earnings: list[RideClimbEarning],
) -> list[RideClimbEarning]:
    """Keep athletic climb facts while removing unreleased economic facts."""
    return [
        earning.model_copy(
            update={
                "cal_tribute": None,
                "tribute_truth_source": TruthSource.projected,
                "tribute_bound": False,
            }
        )
        for earning in earnings
    ]


def _query_table_rows(client: Any, table_name: str, select: str) -> Optional[Any]:
    table = getattr(client, "table", None)
    if not callable(table):
        return None
    return table(table_name).select(select)


def _record_board_standing(
    client: Any,
    vault_ids: list[int],
    wallet: Optional[str],
) -> dict[int, dict[str, Optional[int]]]:
    """This wallet's place and time on each vault's chain-indexed Record Board.

    Reads ``indexed_leaderboards`` (the chain projection the Record Board
    route serves) and ranks it the same way; absent truth is omitted.
    """
    if not wallet or not vault_ids:
        return {}
    try:
        query = _query_table_rows(client, "indexed_leaderboards", "vault_id,entries")
        if query is None:
            return {}
        rows = _safe_rows(query.in_("vault_id", vault_ids).execute())
    except Exception:
        return {}

    standing: dict[int, dict[str, Optional[int]]] = {}
    for row in rows:
        vault_id = _optional_int(row.get("vault_id"))
        entries = row.get("entries")
        if isinstance(entries, str):
            try:
                entries = json.loads(entries)
            except ValueError:
                continue
        if vault_id is None or not isinstance(entries, list):
            continue
        try:
            ranked = project_competition_entries(
                [entry for entry in entries if isinstance(entry, dict)]
            )
        except (TypeError, ValueError):
            continue
        for entry in ranked:
            if str(entry.get("user") or "") == str(wallet):
                standing[vault_id] = {
                    "rank": _optional_int(entry.get("position")),
                    "time_s": _optional_int(entry.get("time_s")),
                }
                break
    return standing


def _fetch_ordinary_ride_economic_steps(
    repo: DatabaseRepository,
    ride_id: str,
) -> list[dict[str, Any]]:
    """Fetch the frozen economic plan's completion steps for one ride.

    Steps are the authoritative pattern -> vault binding: each row carries the
    ``pattern_id`` of the climb pattern that earned the completion plus the
    exact tribute frozen for it. Read-only; failures degrade to an empty list.
    """

    client = getattr(repo, "client", None)
    if client is None:
        return []
    try:
        query = _query_table_rows(
            client,
            "ride_economic_completion_steps",
            "step_index,pattern_id,vault_id,vault_signature,completion_time_s,"
            "exact_tribute_base_units,intensity_bps,state",
        )
        if query is None:
            return []
        rows = _safe_rows(query.eq("ride_id", ride_id).order("step_index").execute())
        return rows
    except Exception:
        return []


def _fetch_terminal_threshold_release_authority(
    repo: DatabaseRepository,
    ride_id: str,
    ride: Optional[dict[str, Any]] = None,
) -> tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]:
    """Resolve one held-ride lifecycle with a single joined production read."""

    # Only a ride frozen at the network default can have a child release.
    # This guard removes all release-table work from ordinary ride detail.
    if (
        ride is not None
        and "reward_ftp_source" in ride
        and ride.get("reward_ftp_source") != "network_default"
    ):
        return ("absent", None, [])
    if (
        ride is not None
        and "processing_status" in ride
        and str(ride.get("processing_status") or "pending")
        not in CLIMB_EARNING_READY_STATUSES
    ):
        return ("absent", None, [])

    client = getattr(repo, "client", None)
    if client is None:
        return ("absent", None, [])

    # Avoid treating unittest-style dynamic mocks as production RPC clients:
    # an explicit instance override supports table fakes, while a real client
    # exposes ``rpc`` on its class.
    rpc = vars(client).get("rpc")
    if rpc is None and callable(getattr(type(client), "rpc", None)):
        rpc = getattr(client, "rpc")
    resolved_status = "terminal"
    if callable(rpc):
        try:
            response = rpc(
                "resolve_reward_threshold_release_lifecycle",
                {"p_ride_id": ride_id},
            ).execute()
            payload = getattr(response, "data", None)
            if isinstance(payload, list):
                payload = payload[0] if payload else None
        except Exception:
            return ("invalid", None, [])
        if not isinstance(payload, dict):
            return ("invalid", None, [])
        lifecycle = str(payload.get("status") or "invalid")
        if lifecycle not in {
            "absent", "held", "lapsed", "planning", "not_counted",
            "under_review", "releasing", "released",
        }:
            return ("invalid", None, [])
        if lifecycle != "released":
            return (lifecycle, None, [])
        if (
            payload.get("execution_state") != "complete"
            or not payload.get("terminal_projected_at")
            or not isinstance(payload.get("snapshot"), dict)
            or not isinstance(payload.get("steps"), list)
        ):
            return ("invalid", None, [])
        snapshot = payload["snapshot"]
        steps = payload["steps"]
        resolved_status = "released"
    else:
        # Compatibility path for local table fakes. Production Supabase clients
        # use the joined resolver above, never these sequential reads.
        try:
            query = _query_table_rows(
                client,
                "reward_threshold_release_snapshots",
                "id,ride_id,exact_cal_base_units,exact_tribute_budget_base_units,"
                "snapshot_evidence",
            )
            if query is None:
                return ("invalid", None, [])
            snapshot_rows = _safe_rows(
                query.eq("ride_id", ride_id).limit(2).execute()
            )
        except Exception:
            return ("invalid", None, [])
        if not snapshot_rows:
            return ("absent", None, [])
        if len(snapshot_rows) != 1:
            return ("invalid", None, [])
        snapshot = snapshot_rows[0]
        snapshot_id = snapshot.get("id")
        try:
            query = _query_table_rows(
                client,
                "reward_threshold_release_executions",
                "snapshot_id,state,terminal_projected_at",
            )
            execution_rows = _safe_rows(
                query.eq("snapshot_id", snapshot_id).limit(2).execute()
            ) if query is not None else []
        except Exception:
            return ("invalid", None, [])
        if len(execution_rows) != 1:
            return ("invalid", None, [])
        execution = execution_rows[0]
        if execution.get("state") != "complete":
            return ("pending", None, [])
        if not execution.get("terminal_projected_at"):
            return ("invalid", None, [])
        try:
            query = _query_table_rows(
                client,
                "reward_threshold_release_steps",
                "snapshot_id,step_index,pattern_id,vault_id,vault_signature,"
                "completion_time_s,exact_tribute_base_units,"
                "completion_evidence_version,completion_evidence_hash,"
                "expected_receipt_pda,state,chain_confirmed_at,projected_at",
            )
            steps = _safe_rows(
                query.eq("snapshot_id", snapshot_id).order("step_index").execute()
            ) if query is not None else []
        except Exception:
            return ("invalid", None, [])

    snapshot_id = snapshot.get("id")
    if not snapshot_id or str(snapshot.get("ride_id") or "") != ride_id:
        return ("invalid", None, [])

    ride_cal = _exact_base_units(snapshot.get("exact_cal_base_units"))
    tribute_budget = _exact_base_units(
        snapshot.get("exact_tribute_budget_base_units")
    )
    if (
        ride_cal is None
        or tribute_budget is None
        or tribute_budget > ride_cal
    ):
        return ("invalid", None, [])

    seen_step_indexes: set[int] = set()
    seen_vault_ids: set[int] = set()
    seen_signatures: set[str] = set()
    tribute_sum = 0
    for step in steps:
        step_index = _optional_int(step.get("step_index"))
        vault_id = _optional_int(step.get("vault_id"))
        completion_time_s = _optional_int(step.get("completion_time_s"))
        tribute = _exact_base_units(step.get("exact_tribute_base_units"))
        signature = str(step.get("vault_signature") or "")
        if (
            str(step.get("snapshot_id") or "") != str(snapshot_id)
            or step_index is None
            or step_index < 0
            or step_index in seen_step_indexes
            or vault_id is None
            or vault_id < 0
            or vault_id in seen_vault_ids
            or not signature
            or signature in seen_signatures
            or not step.get("pattern_id")
            or completion_time_s is None
            or completion_time_s <= 0
            or tribute is None
            or _optional_int(step.get("completion_evidence_version")) != 3
            or not step.get("completion_evidence_hash")
            or not step.get("expected_receipt_pda")
            or step.get("state") != "projected"
            or not step.get("chain_confirmed_at")
            or not step.get("projected_at")
        ):
            return ("invalid", None, [])
        seen_step_indexes.add(step_index)
        seen_vault_ids.add(vault_id)
        seen_signatures.add(signature)
        tribute_sum += tribute

    snapshot_evidence = snapshot.get("snapshot_evidence")
    release_domain = (
        snapshot_evidence.get("domain")
        if isinstance(snapshot_evidence, dict)
        else None
    )
    if release_domain == "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2":
        tribute_conflicts = tribute_sum != tribute_budget
    elif release_domain == "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1":
        tribute_conflicts = tribute_sum > tribute_budget
    else:
        tribute_conflicts = True
    if tribute_conflicts or tribute_sum > ride_cal:
        return ("invalid", None, [])
    return (resolved_status, snapshot, steps)


def _fetch_ride_economic_steps(
    repo: DatabaseRepository,
    ride_id: str,
    ride: Optional[dict[str, Any]] = None,
    release_resolution: Optional[
        tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]
    ] = None,
) -> list[dict[str, Any]]:
    """Select the authoritative pattern-to-Vault binding for one ride."""

    _, steps = _resolve_ride_economic_steps(
        repo, ride_id, ride, release_resolution
    )
    return steps


def _resolve_ride_economic_steps(
    repo: DatabaseRepository,
    ride_id: str,
    ride: Optional[dict[str, Any]] = None,
    release_resolution: Optional[
        tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]
    ] = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Return the selected step authority and its frozen rows."""

    release_status, _, release_steps = release_resolution or (
        _fetch_terminal_threshold_release_authority(repo, ride_id, ride)
    )
    if release_status in {"terminal", "released"}:
        return (release_status, release_steps)
    if release_status == "invalid":
        logger.error(
            "[RideEconomics] Terminal Threshold release authority is incomplete; "
            "withholding economic steps for ride %s",
            ride_id,
        )
        return (release_status, [])
    return (release_status, _fetch_ordinary_ride_economic_steps(repo, ride_id))


def _exact_base_units(value: Any) -> Optional[int]:
    """Parse a DB-sourced exact unsigned base-unit value without float drift."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, str):
        text = value.strip()
        if text.isdigit():
            return int(text)
        return None
    if isinstance(value, float):
        # NUMERIC(20,0) rows should arrive as int/str; a float is only exact
        # while it is integral and inside the 2^53 window.
        if value.is_integer() and 0 <= value <= 2**53:
            return int(value)
        return None
    return None


def _client_threshold_release_status(status: str) -> Optional[str]:
    if status in {"terminal", "released"}:
        return "released"
    if status == "pending":
        return "releasing"
    if status in {
        "held", "lapsed", "planning", "not_counted",
        "under_review", "releasing",
    }:
        return status
    return None


def _fetch_ride_cal_itemization(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
    release_resolution: Optional[
        tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]
    ] = None,
) -> Optional[RideCalItemization]:
    """Build the truthful per-climb CAL itemization for a completed ride.

    Source is the terminal frozen authority: an ordinary economic plan and
    steps, or the immutable child snapshot and projected steps after a
    Threshold release completes. Per PROTOCOL_TRUTHS the rider's credited CAL
    is never reduced by tribute. The display partitions the ride-sized
    conservation ceiling into exact climb flow-meter amounts and "everything
    between"; it does not describe another mint or a rider deduction. Rides
    without a complete authority return ``None`` (truthful absence) rather
    than an invented allocation.
    """

    if (ride.get("processing_status") or "") != "completed":
        return None
    client = getattr(repo, "client", None)
    if client is None:
        return None

    release_status, release_snapshot, release_steps = release_resolution or (
        _fetch_terminal_threshold_release_authority(repo, ride_id, ride)
    )
    is_threshold_release = release_status in {"terminal", "released"}
    if release_status == "invalid":
        logger.error(
            "[RideCalItemization] Terminal Threshold release authority is "
            "incomplete; withholding itemization for ride %s",
            ride_id,
        )
        return None

    if is_threshold_release:
        if release_snapshot is None:
            return None
        plan = release_snapshot
        steps = release_steps
    else:
        try:
            query = _query_table_rows(
                client,
                "ride_economic_plans",
                "ride_id,state,policy_version,exact_cal_base_units,"
                "exact_tribute_base_units,exact_tribute_budget_base_units,"
                "tribute_policy_version,reward_policy",
            )
            if query is None:
                return None
            plan_rows = _safe_rows(query.eq("ride_id", ride_id).limit(1).execute())
        except Exception:
            return None
        if not plan_rows:
            return None
        plan = plan_rows[0]
        if plan.get("state") != "complete":
            return None
        steps = _fetch_ordinary_ride_economic_steps(repo, ride_id)

    ride_cal = _exact_base_units(plan.get("exact_cal_base_units"))
    if ride_cal is None:
        return None

    climbs: list[RideCalItemizationClimb] = []
    tribute_sum = 0
    vault_ids: list[int] = []
    for step in steps:
        tribute = _exact_base_units(step.get("exact_tribute_base_units"))
        vault_id = _optional_int(step.get("vault_id"))
        pattern_id = step.get("pattern_id")
        signature = step.get("vault_signature")
        if tribute is None or vault_id is None or not pattern_id or not signature:
            logger.warning(
                "[RideCalItemization] Frozen step is not exactly representable; "
                "withholding itemization for ride %s",
                ride_id,
            )
            return None
        tribute_sum += tribute
        vault_ids.append(vault_id)
        climbs.append(
            RideCalItemizationClimb(
                pattern_id=str(pattern_id),
                vault_id=vault_id,
                vault_signature=str(signature),
                cal_tribute_base_units=str(tribute),
                completion_time_s=_optional_int(step.get("completion_time_s")),
                intensity_bps=_optional_int(step.get("intensity_bps")),
            )
        )

    if tribute_sum > ride_cal:
        logger.error(
            "[RideCalItemization] Frozen tribute exceeds ride CAL for ride %s "
            "(tribute=%s, ride=%s); withholding itemization",
            ride_id,
            tribute_sum,
            ride_cal,
        )
        return None
    if is_threshold_release:
        plan_budget = _exact_base_units(
            plan.get("exact_tribute_budget_base_units")
        )
        snapshot_evidence = plan.get("snapshot_evidence")
        release_domain = (
            snapshot_evidence.get("domain")
            if isinstance(snapshot_evidence, dict)
            else None
        )
        if release_domain == "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2":
            tribute_conflicts = plan_budget != tribute_sum
            resolved_tribute_policy = CAL_TRIBUTE_POLICY_VERSION
        elif release_domain == "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1":
            tribute_conflicts = plan_budget is None or tribute_sum > plan_budget
            resolved_tribute_policy = "cal_tribute_segment_np_fixed_10pct_v1"
        else:
            tribute_conflicts = True
            resolved_tribute_policy = ""
        if tribute_conflicts:
            logger.error(
                "[RideCalItemization] Threshold release tribute exceeds or "
                "conflicts with its frozen budget for ride %s; withholding "
                "itemization",
                ride_id,
            )
            return None
    else:
        plan_budget = _exact_base_units(
            plan.get("exact_tribute_budget_base_units")
        )
        plan_tribute = _exact_base_units(plan.get("exact_tribute_base_units"))
        tribute_policy = plan.get("tribute_policy_version")
        if tribute_policy == "cal_tribute_segment_tss_v2":
            tribute_conflicts = plan_budget != tribute_sum
        elif tribute_policy == "cal_tribute_segment_np_fixed_10pct_v1":
            tribute_conflicts = plan_budget is None or tribute_sum > plan_budget
        elif (
            tribute_policy is None
            and plan.get("reward_policy") == "threshold_provisional_hold_v1"
        ):
            tribute_conflicts = plan_budget is not None or tribute_sum != 0
        else:
            tribute_conflicts = True
        resolved_tribute_policy = str(tribute_policy or "")
        if tribute_conflicts or plan_tribute != tribute_sum:
            logger.error(
                "[RideCalItemization] Plan tribute total %s does not equal step sum "
                "%s for ride %s; withholding itemization",
                plan_tribute,
                tribute_sum,
                ride_id,
            )
            return None

    if climbs and vault_ids:
        try:
            query = _query_table_rows(client, "indexed_vaults", "id,name")
            if query is not None:
                vault_rows = _safe_rows(query.in_("id", sorted(set(vault_ids))).execute())
                names = {
                    _optional_int(row.get("id")): row.get("name")
                    for row in vault_rows
                }
                for climb in climbs:
                    climb.climb_name = names.get(climb.vault_id)
        except Exception:
            pass

    return RideCalItemization(
        tribute_policy_version=resolved_tribute_policy,
        ride_cal_base_units=str(ride_cal),
        tribute_budget_base_units=str(plan_budget),
        climbs=climbs,
        everything_between_base_units=str(ride_cal - tribute_sum),
    )


def _fetch_ride_climb_earnings(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
    release_resolution: Optional[
        tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]
    ] = None,
) -> list[RideClimbEarning]:
    """Fetch climb-level earnings for the post-ride client contract.

    This is deliberately projection-backed. The route does not compute CAL or
    placements itself; it only joins read models produced by ride processing
    and the indexer.
    """

    client = getattr(repo, "client", None)
    if client is None:
        return []

    step_authority, economic_steps = _resolve_ride_economic_steps(
        repo, ride_id, ride, release_resolution
    )
    if step_authority == "invalid":
        return []

    completion_rows: list[dict[str, Any]] = []
    completion_selects = (
        (
            "vault_signature,wallet,activity_id,time_seconds,best_time_seconds,"
            "is_pr,completed_at,on_chain_tx,cal_tribute,chain_confirmation_status,"
            "completion_receipt_pda,completion_evidence_hash,"
            "completion_evidence_version,chain_confirmed_at"
        ),
        (
            "vault_signature,wallet,activity_id,time_seconds,best_time_seconds,"
            "is_pr,completed_at,on_chain_tx"
        ),
    )
    for select in completion_selects:
        try:
            query = _query_table_rows(client, "vault_completions", select)
            if query is None:
                return []
            response = query.eq("activity_id", ride_id).execute()
            completion_rows = _safe_rows(response)
            break
        except Exception:
            completion_rows = []

    if not completion_rows:
        return []

    completion_rows = [
        row for row in completion_rows if is_authoritative_completion(row)
    ]
    if not completion_rows:
        return []

    signatures = sorted(
        {
            str(row.get("vault_signature"))
            for row in completion_rows
            if row.get("vault_signature")
        }
    )
    if not signatures:
        return []

    vault_by_signature: dict[str, dict[str, Any]] = {}
    try:
        query = _query_table_rows(client, "indexed_vaults", "id,name,signature_hex,pda")
        if query is not None:
            vault_rows = _safe_rows(
                query.in_("signature_hex", signatures).execute()
            )
            vault_by_signature = {
                str(row.get("signature_hex")): row
                for row in vault_rows
                if row.get("signature_hex")
            }
    except Exception:
        vault_by_signature = {}

    # Frozen plan steps carry the authoritative pattern -> vault binding.
    pattern_by_signature: dict[str, str] = {
        str(step.get("vault_signature")): str(step.get("pattern_id"))
        for step in economic_steps
        if step.get("vault_signature") and step.get("pattern_id")
    }

    wallet = (
        ride.get("wallet")
        or ride.get("user_wallet")
        or next((row.get("wallet") for row in completion_rows if row.get("wallet")), None)
    )
    board_by_vault_id = _record_board_standing(
        client,
        sorted(
            {
                vault_id
                for vault_id in (
                    _optional_int(row.get("id")) for row in vault_by_signature.values()
                )
                if vault_id is not None
            }
        ),
        wallet,
    )

    climb_earnings: list[RideClimbEarning] = []
    for row in completion_rows:
        signature = row.get("vault_signature")
        if not signature:
            continue
        signature = str(signature)
        vault = vault_by_signature.get(signature, {})
        vault_id = _optional_int(vault.get("id"))
        board = board_by_vault_id.get(vault_id, {}) if vault_id is not None else {}
        rank = board.get("rank")
        board_best_time = board.get("time_s")
        completion_time = _optional_int(row.get("time_seconds"))
        tx_signature = row.get("on_chain_tx")
        authoritative_onchain = is_authoritative_completion(row)
        authoritative_tribute = is_authoritative_tribute(row)
        evidence_version = _optional_int(row.get("completion_evidence_version"))

        climb_earnings.append(
            RideClimbEarning(
                truth_source=(
                    TruthSource.onchain
                    if authoritative_onchain
                    else TruthSource.projected
                ),
                ride_id=ride_id,
                climb_id=str(vault_id if vault_id is not None else signature),
                climb_name=vault.get("name"),
                pattern_id=pattern_by_signature.get(signature),
                vault_id=vault_id,
                vault_signature=signature,
                cal_tribute=_optional_int(row.get("cal_tribute")),
                tribute_truth_source=(
                    TruthSource.onchain
                    if authoritative_tribute
                    else TruthSource.projected
                ),
                completion_evidence_version=evidence_version,
                tribute_bound=authoritative_tribute,
                completion_time_s=completion_time,
                record_board_rank=rank,
                record_board_best_time_s=board_best_time,
                is_new_personal_best=(
                    bool(row.get("is_pr")) if row.get("is_pr") is not None else None
                ),
                is_new_kom=(
                    rank == 1
                    and completion_time is not None
                    and board_best_time is not None
                    and completion_time == board_best_time
                ),
                tx_signature=tx_signature,
                completed_at=row.get("completed_at"),
            )
        )

    climb_earnings.sort(key=lambda earning: str(earning.completed_at or ""))
    return climb_earnings


def _fetch_ride_climb_earnings_for_client(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
    release_resolution: Optional[
        tuple[str, Optional[dict[str, Any]], list[dict[str, Any]]]
    ] = None,
) -> list[RideClimbEarning]:
    include_economy = _threshold_economy_visible(ride)
    earnings = _fetch_ride_climb_earnings(
        repo,
        ride_id,
        ride,
        release_resolution,
    )
    return earnings if include_economy else _withhold_climb_economy(earnings)


def _fetch_pattern_vault_matches(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    """Build real per-pattern vault-match facts for the patterns endpoint.

    Keyed by climb pattern id. A pattern gets a ``vaultMatch`` only when this
    ride produced an authoritative on-chain-backed completion for it (frozen
    plan step + confirmed completion projection). Every emitted field is read
    from a real projection: this ride's time and PR flag from
    ``vault_completions``, the all-time best from ``indexed_completions``, the
    Record Board rank from ``indexed_leaderboards``, and KOM facts from
    ``indexed_vaults``. Absent truth is omitted, never invented.
    """

    client = getattr(repo, "client", None)
    if client is None:
        return {}

    steps = _fetch_ride_economic_steps(repo, ride_id, ride)
    if not steps:
        return {}

    signatures = sorted(
        {
            str(step.get("vault_signature"))
            for step in steps
            if step.get("vault_signature")
        }
    )
    if not signatures:
        return {}

    completion_by_signature: dict[str, dict[str, Any]] = {}
    try:
        query = _query_table_rows(
            client,
            "vault_completions",
            "vault_signature,wallet,activity_id,time_seconds,is_pr,"
            "chain_confirmation_status,on_chain_tx,completion_receipt_pda,"
            "completion_evidence_hash,chain_confirmed_at",
        )
        if query is not None:
            rows = _safe_rows(
                query.eq("activity_id", ride_id).in_("vault_signature", signatures).execute()
            )
            completion_by_signature = {
                str(row.get("vault_signature")): row
                for row in rows
                if row.get("vault_signature") and is_authoritative_completion(row)
            }
    except Exception:
        completion_by_signature = {}
    if not completion_by_signature:
        return {}

    vault_by_id: dict[int, dict[str, Any]] = {}
    vault_ids = sorted(
        {
            _optional_int(step.get("vault_id"))
            for step in steps
            if _optional_int(step.get("vault_id")) is not None
        }
    )
    try:
        query = _query_table_rows(
            client,
            "indexed_vaults",
            "id,name,signature_hex,kom_holder,kom_time_s,canon_climb_id",
        )
        if query is not None:
            rows = _safe_rows(query.in_("id", vault_ids).execute())
            vault_by_id = {
                _optional_int(row.get("id")): row
                for row in rows
                if _optional_int(row.get("id")) is not None
            }
    except Exception:
        vault_by_id = {}

    wallet = ride.get("wallet") or ride.get("user_wallet") or next(
        (row.get("wallet") for row in completion_by_signature.values() if row.get("wallet")),
        None,
    )

    board_by_vault_id = _record_board_standing(client, vault_ids, wallet)

    best_by_vault_id: dict[int, Optional[int]] = {}
    if wallet and vault_ids:
        try:
            query = _query_table_rows(
                client, "indexed_completions", "vault_id,best_time_s"
            )
            if query is not None:
                rows = _safe_rows(
                    query.eq("user_pubkey", wallet).in_("vault_id", vault_ids).execute()
                )
                best_by_vault_id = {
                    _optional_int(row.get("vault_id")): _optional_int(row.get("best_time_s"))
                    for row in rows
                    if _optional_int(row.get("vault_id")) is not None
                }
        except Exception:
            best_by_vault_id = {}

    matches: dict[str, dict[str, Any]] = {}
    for step in steps:
        pattern_id = step.get("pattern_id")
        signature = str(step.get("vault_signature") or "")
        vault_id = _optional_int(step.get("vault_id"))
        if not pattern_id or not signature or vault_id is None:
            continue
        completion = completion_by_signature.get(signature)
        if completion is None:
            continue
        vault = vault_by_id.get(vault_id, {})
        your_time = _optional_int(completion.get("time_seconds"))
        if your_time is None:
            your_time = _optional_int(step.get("completion_time_s"))
        kom_time = _optional_int(vault.get("kom_time_s"))
        best_time = best_by_vault_id.get(vault_id)
        canon_climb_id = vault.get("canon_climb_id")
        match: dict[str, Any] = {
            "id": str(vault_id),
            "vaultId": vault_id,
            # Canon registry climb UUID — the climb-sheet navigation key.
            "vaultClimbId": str(canon_climb_id) if canon_climb_id else None,
            "name": vault.get("name"),
            "yourTime": your_time,
            "isPR": (
                bool(completion.get("is_pr"))
                if completion.get("is_pr") is not None
                else None
            ),
            "yourBestTime": best_time if best_time else None,
            "yourRank": board_by_vault_id.get(vault_id, {}).get("rank"),
            "komTime": kom_time if kom_time else None,
            "komHolder": vault.get("kom_holder") or None,
        }
        matches[str(pattern_id)] = match
    return matches


def _build_ride_progression(ride_id: str, ride: dict[str, Any]) -> Optional[RideProgression]:
    tss_delta = _optional_float(ride.get("tss"))
    total_tss_after = _optional_float(ride.get("total_tss_after"))
    level_delta = _optional_int(ride.get("level_delta"))
    level_after = _optional_int(ride.get("level_after"))
    if (
        tss_delta is None
        and total_tss_after is None
        and level_delta is None
        and level_after is None
    ):
        return None
    return RideProgression(
        ride_id=ride_id,
        tss_delta=tss_delta,
        total_tss_after=total_tss_after,
        level_delta=level_delta,
        level_after=level_after,
    )


def _build_ride_effort_economy(ride: dict[str, Any]) -> Optional[RideEffortEconomy]:
    values = {
        "effort_evidence_tier": ride.get("effort_evidence_tier"),
        "reward_policy": ride.get("reward_policy"),
        "threshold_economy_state": ride.get("threshold_economy_state"),
        "estimated_cal": _optional_int(ride.get("estimated_cal")),
        "rewardable_cal": _optional_int(ride.get("rewardable_cal")),
        "tributable_cal": _optional_int(ride.get("tributable_cal")),
        "threshold_release_status": ride.get("_threshold_release_status"),
    }
    if all(value is None for value in values.values()):
        return None
    return RideEffortEconomy(**values)


def _build_ride_status_response(
    ride_id: str,
    ride: dict[str, Any],
    climb_earnings: Optional[list[RideClimbEarning]] = None,
    *,
    include_economy: bool = True,
) -> dict[str, Any]:
    """Build the canonical client.v1 ride status response.

    The route may expose progressive processing details, but the shape must
    remain governed by ``RideStatusResponse`` so clients do not learn a
    route-local contract outside the protocol truth boundary.
    """

    status = ride.get("processing_status") or "pending"
    metrics = None
    has_gps = False
    has_patterns = False
    has_leaderboards = False
    has_achievements = False
    cal_earned = None
    dung_minted = None
    tx_signature = None
    earnings = None

    if status in ("metrics_ready", "enriched", "completed", "under_review"):
        metrics = RideStatusMetrics(
            tss=ride.get("tss"),
            training_metrics=ride.get("training_metrics"),
            moving_time_sec=(ride.get("training_metrics") or {}).get("moving_s"),
            recording_time_sec=(ride.get("training_metrics") or {}).get("recording_s"),
            threshold_training_state=ride.get("threshold_training_state"),
            kcals=ride.get("kcals"),
            distance_m=ride.get("distance_m"),
            elevation_gain_m=ride.get("elevation_gain_m"),
            duration_sec=ride.get("duration_sec"),
            avg_power_w=ride.get("avg_power_w"),
            normalized_power_w=ride.get("normalized_power_w"),
        )
        has_gps = True

    if status in ("enriched", "completed", "under_review"):
        has_patterns = True
    if status in ("enriched", "completed"):
        has_leaderboards = True

    if status == "completed":
        cal_earned = ride.get("cal_earned")
        dung_minted = ride.get("dung_minted")
        tx_signature = ride.get("tx_signature")
        has_achievements = True
        if cal_earned is not None or dung_minted is not None:
            earnings = RideEarnings(
                ride_id=ride_id,
                cal_earned=cal_earned,
                dung_earned=dung_minted,
                finalized_at=ride.get("finalized_at"),
            )

    response = RideStatusResponse(
        subject_states=ride_subject_states({**ride, "id": ride_id}),
        ride_id=ride_id,
        effort_seconds=ride.get("effort_seconds"),
        covered_effort_seconds=ride.get("covered_effort_seconds"),
        paid_effort_seconds=ride.get("paid_effort_seconds"),
        status=status,
        attestation_status=_derive_attestation_status(ride),
        ride_hash_hex=ride.get("ride_hash_hex"),
        attestation_commitment_hex=ride.get("attestation_commitment_hex"),
        parser_version=ride.get("ride_parser_version"),
        preliminary_ride_hash_hex=ride.get("preliminary_ride_hash_hex"),
        preliminary_parser_version=ride.get("preliminary_parser_version"),
        canonical_match=ride.get("canonical_match"),
        review_reason=ride.get("review_reason"),
        ride_attestation_pda=ride.get("ride_attestation_pda"),
        ride_attestation_tx_signature=ride.get("ride_attestation_tx_signature"),
        ride_attested_at=ride.get("ride_attested_at"),
        finalized_at=ride.get("finalized_at"),
        import_source=ride.get("import_source"),
        import_source_id=ride.get("import_source_id"),
        import_diagnostics=ride.get("import_diagnostics"),
        error_message=ride.get("error_message"),
        processing_stage=_derive_processing_stage(ride),
        can_retry_processing=_can_retry_processing(ride),
        failure=_derive_processing_failure(ride),
        input_quality=_derive_input_quality(ride),
        phase1_error=ride.get("phase1_error"),
        phase2_error=ride.get("phase2_error"),
        phase3_error=ride.get("phase3_error"),
        phase1_completed_at=ride.get("phase1_completed_at"),
        phase2_completed_at=ride.get("phase2_completed_at"),
        phase3_completed_at=ride.get("phase3_completed_at"),
        phase1_duration_ms=ride.get("phase1_duration_ms"),
        phase2_duration_ms=ride.get("phase2_duration_ms"),
        phase3_duration_ms=ride.get("phase3_duration_ms"),
        metrics=metrics,
        has_gps=has_gps,
        has_patterns=has_patterns,
        has_leaderboards=has_leaderboards,
        has_achievements=has_achievements,
        cal_earned=cal_earned,
        dung_minted=dung_minted,
        tx_signature=tx_signature,
        earnings=earnings,
        effort_policy=_build_ride_effort_economy(ride),
        climb_earnings=climb_earnings or [],
        progression=_build_ride_progression(ride_id, ride),
    ).model_dump(mode="json")
    if include_economy:
        return response

    response["subject_states"].pop("cal", None)
    for field in ("effort_seconds", "covered_effort_seconds", "paid_effort_seconds"):
        response.pop(field, None)
    response.pop("cal_earned", None)
    response.pop("dung_minted", None)
    response.pop("earnings", None)
    effort_policy = response.get("effort_policy")
    if isinstance(effort_policy, dict):
        for field in ("estimated_cal", "rewardable_cal", "tributable_cal"):
            effort_policy.pop(field, None)
        if all(value is None for value in effort_policy.values()):
            response.pop("effort_policy", None)
    for earning in response.get("climb_earnings") or []:
        if isinstance(earning, dict):
            earning.pop("cal_tribute", None)
    return response


def _ride_place_label(data: dict[str, Any]) -> Optional[str]:
    # One source chain, shared with processing-time title generation.
    return place_label_for_ride(data)


def _elevation_correction_info(data: dict[str, Any]) -> Optional[ElevationCorrectionInfo]:
    """DEM correction provenance for a ride row; None = never attempted."""
    correction_status = data.get("elevation_correction_status")
    if not isinstance(correction_status, str) or not correction_status:
        return None
    return ElevationCorrectionInfo(
        status=correction_status,
        source_version=data.get("elevation_correction_source"),
        correction_version=data.get("elevation_correction_version"),
        coverage_bps=_optional_int(data.get("elevation_correction_coverage_bps")),
        reason=data.get("elevation_correction_reason"),
    )


def _attach_corrected_elevation(
    data: dict[str, Any],
    points: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Zip the stored corrected-elevation projection onto decoded GPS points.

    Runs BEFORE viewer privacy projection so the value travels with each point
    through any trimming. Points without a trustworthy corrected value carry
    ``elevation_corrected_m: None`` — clients gap the relief line, never zero.
    """

    corrected: list[Optional[float]] = []
    if data.get("elevation_correction_status") == "corrected":
        corrected = decode_correction_profile(data.get("elevation_correction_profile"))
    for index, point in enumerate(points):
        point["elevation_corrected_m"] = (
            corrected[index] if index < len(corrected) else None
        )
    return points


def _decode_ride_gps_points(data: dict[str, Any]) -> list[dict[str, Any]]:
    gps_track = data.get("gps_track")
    if not gps_track:
        return []
    try:
        from ..utils.polyline import decode_gps_track
        return decode_gps_track(gps_track)
    except Exception:
        return []


def _empty_ride_stream_response(
    ride_id: str,
    stream_type: str,
    *,
    redacted: bool = False,
) -> dict[str, Any]:
    response: dict[str, Any] = {
        "id": None,
        "ride_id": ride_id,
        "stream_type": stream_type,
        "timestamps": [],
        "values": [],
        "sample_count": 0,
        "min_value": None,
        "max_value": None,
        "avg_value": None,
    }
    if redacted:
        response["redacted"] = True
    return response


ROUTE_RECONSTRUCTION_PATTERN_FIELDS = {
    "activity_id",
    "activityId",
    "end_idx",
    "endIdx",
    "end_lat",
    "endLat",
    "end_lon",
    "endLon",
    "end_offset_s",
    "endOffsetS",
    "end_time_offset_s",
    "endTimeOffsetS",
    "h3_tile_ids",
    "h3TileIds",
    "lat",
    "latitude",
    "lon",
    "longitude",
    "match_trace",
    "matchTrace",
    "signature_hex",
    "signatureHex",
    "start_idx",
    "startIdx",
    "start_lat",
    "startLat",
    "start_lon",
    "startLon",
    "start_offset_s",
    "startOffsetS",
    "start_time_offset_s",
    "startTimeOffsetS",
    "tile_ids",
    "tileIds",
    "user_id",
    "userId",
    "wallet",
}


def _redact_pattern_route_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [_redact_pattern_route_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _redact_pattern_route_fields(item)
        for key, item in value.items()
        if key not in ROUTE_RECONSTRUCTION_PATTERN_FIELDS
    }


# Owner-only pattern facts (boulderroller-v2-pvrwy). Average power and NP in
# watts stay public; these reach the ride's owner alone.
# W/kg reveals body weight (weight = avg power / W/kg). Tim, 19 Oct 2026: other
# viewers see W/kg only with the rider's explicit share_wkg opt-in (default off).
RIDER_WEIGHT_PATTERN_FIELDS = frozenset({"w_per_kg", "wPerKg", "weight_kg", "weightKg"})
# A ratio against the rider's FTP or Threshold reveals it (FTP = NP / IF, and
# NP is public), so IF, % of FTP and training stress stay with the owner too.
RIDER_THRESHOLD_PATTERN_FIELDS = frozenset({
    "intensity_index",
    "intensityIndex",
    "intensity_factor",
    "intensityFactor",
    "intensity_pct",
    "intensityPct",
    "tss",
    "load",
    "threshold", "power_zone_tops_w", "power_zone_s", "max_hr_bpm",
    "percent_of_threshold", "threshold_pct", "powerZoneTopsW", "powerZoneS", "maxHrBpm",
})
OWNER_ONLY_PATTERN_FIELDS = RIDER_WEIGHT_PATTERN_FIELDS | RIDER_THRESHOLD_PATTERN_FIELDS


def _withhold_owner_only_pattern_fields(value: Any, *, share_wkg: bool = False) -> Any:
    if isinstance(value, list):
        return [_withhold_owner_only_pattern_fields(item, share_wkg=share_wkg) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: _withhold_owner_only_pattern_fields(item, share_wkg=share_wkg)
        for key, item in value.items()
        if key not in OWNER_ONLY_PATTERN_FIELDS or (share_wkg and key in {"w_per_kg", "wPerKg"})
    }


async def _privacy_zones_for_projection(
    repo: DatabaseRepository,
    user_id: str,
) -> list[dict[str, Any]]:
    try:
        response = await repo._run(
            lambda: repo._client.table("privacy_zones")
            .select("latitude,longitude,radius_m")
            .eq("user_id", user_id)
            .execute()
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route privacy is temporarily unavailable. Please retry.",
        ) from exc
    zones = getattr(response, "data", None)
    if zones is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route privacy is temporarily unavailable. Please retry.",
        )
    return [dict(zone) for zone in zones]


async def _project_route_for_viewer(
    data: dict[str, Any],
    points: list[dict[str, Any]],
    decision: VisibilityDecision,
    repo: DatabaseRepository,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Project points for this viewer; also return the privacy zones applied
    so downstream preview simplification can honor the same edge law."""
    if decision.is_owner:
        return points, []

    try:
        policy = RidePrivacyPolicy.from_values(
            visibility=decision.visibility,
            map_visibility=decision.map_visibility,
            map_hide_start_m=decision.map_hide_start_m,
            map_hide_end_m=decision.map_hide_end_m,
        )
        zones = [] if policy.map_visibility == "hide_entire" else await _privacy_zones_for_projection(
            repo,
            str(data.get("user_id") or data.get("rider_id") or ""),
        )
        return project_route_points(
            points,
            policy,
            privacy_zones=zones,
            is_owner=False,
        ), zones
    except PrivacySettingsUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route privacy is temporarily unavailable. Please retry.",
        ) from exc


async def _route_preview_points_for_record(
    data: dict[str, Any],
    decision: VisibilityDecision,
    repo: DatabaseRepository,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Viewer-projected preview points plus the privacy zones applied, so the
    preview builder can keep its simplified edges under the same zone law."""
    points = _decode_ride_gps_points(data)
    return await _project_route_for_viewer(data, points, decision, repo)


async def _resolve_write_privacy_policy(
    ride_repo: RideRepository,
    user_id: str,
    request: Union[RideUploadRequest, UploadInitRequest],
) -> RidePrivacyPolicy:
    """Freeze a complete ride policy before a new upload can mutate storage."""
    try:
        policy = await ride_repo.resolve_ride_privacy_policy(
            user_id,
            visibility=request.visibility,
            map_visibility=request.map_visibility,
            map_hide_start_m=request.map_hide_start_m,
            map_hide_end_m=request.map_hide_end_m,
        )
    except PrivacySettingsUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        ) from exc
    if not isinstance(policy, RidePrivacyPolicy):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Privacy settings are temporarily unavailable. Please retry.",
        )
    return policy


def _resolve_ride_privacy_edit(
    ride: dict[str, Any],
    request: RideUpdateRequest,
) -> RidePrivacyPolicy:
    """Merge a partial edit into one complete, validated ride snapshot."""
    return RidePrivacyPolicy.from_values(
        visibility=(
            request.visibility
            if request.visibility is not None
            else ride.get("visibility")
        ),
        map_visibility=(
            request.map_visibility
            if request.map_visibility is not None
            else ride.get("map_visibility")
        ),
        map_hide_start_m=(
            request.map_hide_start_m
            if request.map_hide_start_m is not None
            else ride.get("map_hide_start_m")
        ),
        map_hide_end_m=(
            request.map_hide_end_m
            if request.map_hide_end_m is not None
            else ride.get("map_hide_end_m")
        ),
    )


def _to_ride_record(
    data: dict[str, Any],
    vault_completions: list[dict] = None,
    privacy: Optional[dict[str, Any]] = None,
    media: Optional[list[RideMedia]] = None,
    cal_itemization: Optional[RideCalItemization] = None,
) -> RideRecord:
    # Patterns replaced segments in the new tile-based architecture
    patterns = data.get("patterns")
    if not isinstance(patterns, list):
        patterns = []

    # Convert vault completions to VaultCompletionInfo objects
    from ..schemas import VaultCompletionInfo
    vc_list = []
    for vc in (vault_completions or []):
        vc_list.append(VaultCompletionInfo(
            vault_id=vc["vault_id"],
            vault_name=vc["vault_name"],
            vault_signature=vc["vault_signature"],
            time_seconds=vc.get("time_seconds"),
        ))

    # Determine processing status and progress flags
    status = data.get("processing_status") or "completed"

    # Progress indicators based on status
    # metrics_ready, enriched, completed, and under_review all have GPS stored.
    has_gps = status in ("metrics_ready", "enriched", "completed", "under_review")
    # under_review rides still carry stored pattern output, but do not expose
    # leaderboard/economic truth as settled until review is resolved.
    has_patterns = status in ("enriched", "completed", "under_review")
    has_leaderboards = status in ("enriched", "completed")
    # completed has achievements (awarded in Phase 3)
    has_achievements = status == "completed"

    route_preview = build_route_preview(
        data.get("_route_preview_points") or [],
        source="server_gps",
        place_label=_ride_place_label(data),
        privacy=privacy,
        privacy_zones=data.get("_route_preview_zones") or [],
    )
    return RideRecord(
        subject_states=ride_subject_states(data),
        effort_seconds=data.get("effort_seconds"),
        covered_effort_seconds=data.get("covered_effort_seconds"),
        paid_effort_seconds=data.get("paid_effort_seconds"),
        id=UUID(str(data.get("id"))),
        rider_id=UUID(str(data.get("user_id"))),
        started_at=_parse_datetime(data.get("started_at")) or datetime.now(),
        completed_at=_parse_datetime(data.get("completed_at")),
        patterns=patterns,
        training_metrics=data.get("training_metrics"),
        moving_time_sec=data.get("moving_time_sec") if data.get("training_metrics") else None,
        recording_time_sec=(data.get("training_metrics") or {}).get("recording_s"),
        calories_burned=data.get("kcals"),
        status=status,
        distance_m=float(data.get("distance_m")) if data.get("distance_m") is not None else None,
        elevation_gain_m=float(data.get("elevation_gain_m")) if data.get("elevation_gain_m") is not None else None,
        duration_sec=int(data.get("duration_sec")) if data.get("duration_sec") is not None else None,
        tss=float(data.get("tss")) if data.get("tss") is not None else None,
        threshold_training_state=data.get("threshold_training_state"),
        # Token earnings
        dung_minted=int(data.get("dung_minted")) if data.get("dung_minted") else None,
        cal_earned=int(data.get("cal_earned")) if data.get("cal_earned") else None,
        effort_evidence_tier=data.get("effort_evidence_tier"),
        reward_policy=data.get("reward_policy"),
        threshold_economy_state=data.get("threshold_economy_state"),
        estimated_cal=int(data.get("estimated_cal")) if data.get("estimated_cal") is not None else None,
        rewardable_cal=int(data.get("rewardable_cal")) if data.get("rewardable_cal") is not None else None,
        tributable_cal=int(data.get("tributable_cal")) if data.get("tributable_cal") is not None else None,
        threshold_release_status=data.get("_threshold_release_status"),
        elevation_corrected_m=_optional_float(data.get("elevation_corrected_gain_m")),
        elevation_correction=_elevation_correction_info(data),
        # rides.title is the rider-visible name (processing default or rider
        # edit); file_name remains the legacy fallback for untitled rides.
        title=data.get("title") or data.get("file_name") or "Ride",
        description=data.get("description"),
        avg_power_w=float(data.get("avg_power_w")) if data.get("avg_power_w") is not None else None,
        normalized_power_w=float(data.get("normalized_power_w")) if data.get("normalized_power_w") is not None else None,
        avg_hr_bpm=float(data.get("avg_hr_bpm")) if data.get("avg_hr_bpm") is not None else None,
        perceived_exertion=_optional_int(data.get("perceived_exertion")),
        weather_temp_c=float(data.get("weather_temp_c")) if data.get("weather_temp_c") is not None else None,
        weather_wind_mps=float(data.get("weather_wind_mps")) if data.get("weather_wind_mps") is not None else None,
        weather_wind_deg=_optional_int(data.get("weather_wind_deg")),
        weather_source=data.get("weather_source"),
        laps=data.get("laps") if isinstance(data.get("laps"), list) else None,
        power_balance=data.get("power_balance") if isinstance(data.get("power_balance"), dict) else None,
        cal_itemization=cal_itemization,
        attestation_status=_derive_attestation_status(data),
        ride_hash_hex=data.get("ride_hash_hex"),
        attestation_commitment_hex=data.get("attestation_commitment_hex"),
        parser_version=int(data.get("ride_parser_version")) if data.get("ride_parser_version") is not None else None,
        preliminary_ride_hash_hex=data.get("preliminary_ride_hash_hex"),
        preliminary_parser_version=int(data.get("preliminary_parser_version")) if data.get("preliminary_parser_version") is not None else None,
        canonical_match=data.get("canonical_match"),
        review_reason=data.get("review_reason"),
        visibility=normalize_visibility(data.get("visibility"), default="public"),
        privacy=PrivacyState(**privacy) if privacy else None,
        ride_attestation_pda=data.get("ride_attestation_pda"),
        ride_attestation_tx_signature=data.get("ride_attestation_tx_signature"),
        ride_attested_at=_parse_datetime(data.get("ride_attested_at")),
        # BACKEND_TRUTHS §3.3 — NULL means the ride's settlement week has
        # not yet finalized on-chain; a value means the ride's economic
        # consequences are immutable.
        finalized_at=_parse_datetime(data.get("finalized_at")),
        vault_completions=vc_list,
        route_preview=route_preview,
        **(data.get("_list_shape") or {}),
        media=media or [],
        # Progress indicators
        has_gps=has_gps,
        has_patterns=has_patterns,
        has_leaderboards=has_leaderboards,
        has_achievements=has_achievements,
    )


def _serialize_ride_record(
    ride_record: RideRecord,
    *,
    is_owner: bool,
    mode: Literal["json", "python"] = "python",
) -> dict[str, Any]:
    payload = ride_record.model_dump(mode=mode, by_alias=True)
    if is_owner:
        return payload
    payload.get("subjectStates", {}).pop("cal", None)
    for field in (
        "uploadedAt",
        "dungEarned",
        "calEarned",
        "estimatedCal",
        "rewardableCal",
        "tributableCal",
        "calItemization",
        "effortSeconds",
        "coveredEffortSeconds",
        "paidEffortSeconds",
    ):
        payload.pop(field, None)
    return payload


async def _serialized_ride_media(
    repo: Any,
    ride_id: str,
) -> list[RideMedia]:
    list_media = getattr(repo, "list_ride_media", None)
    if not list_media:
        return []
    rows_result = list_media(ride_id)
    if not inspect.isawaitable(rows_result):
        return []
    rows = await rows_result
    if not rows:
        return []
    return await serialize_ride_media_list(rows)


async def _serialized_ride_media_for_rides(
    repo: Any,
    ride_ids: list[str],
) -> dict[str, list[RideMedia]]:
    grouped: dict[str, list[RideMedia]] = {ride_id: [] for ride_id in ride_ids}
    list_media = getattr(repo, "list_ride_media_for_rides", None)
    if not list_media:
        return grouped
    rows_result = list_media(ride_ids)
    if not inspect.isawaitable(rows_result):
        return grouped
    rows_by_ride = await rows_result
    if not isinstance(rows_by_ride, dict):
        return grouped
    for ride_id in ride_ids:
        rows = rows_by_ride.get(ride_id) or []
        if rows:
            grouped[ride_id] = await serialize_ride_media_list(rows)
    return grouped


async def _require_owned_ride_media(
    ride_repo: Any,
    *,
    ride_id: str,
    media_id: str,
    current_user: AuthenticatedUser,
) -> dict:
    media = await ride_repo.get_ride_media(media_id)
    if not media or str(media.get("ride_id")) != ride_id:
        raise HTTPException(status_code=404, detail="Ride media not found")
    if media.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride media")
    return media


async def _delete_ride_storage_objects(ride: dict[str, Any], repo: Any) -> int:
    """Delete raw ride file and ride media objects before removing DB rows."""
    paths: dict[str, bool] = {}
    raw_file_path = ride.get("raw_file_path")
    if raw_file_path:
        paths[str(raw_file_path)] = False

    list_media = getattr(repo, "list_ride_media", None)
    if list_media:
        try:
            media_rows = await list_media(str(ride.get("id")), include_uploading=True)
        except TypeError:
            media_rows = await list_media(str(ride.get("id")))
        for row in media_rows or []:
            storage_path = row.get("storage_path")
            if storage_path:
                paths[str(storage_path)] = True

    if not paths:
        return 0

    storage = create_file_storage_service()
    deleted = 0
    for path, is_photo in paths.items():
        try:
            if is_photo:
                deleted += await storage.delete_photo_files(path)
            else:
                deleted += bool(await storage.delete_ride_file(path))
        except Exception as exc:
            logger.error("[Rides] Storage cleanup failed ride_id=%s error=%s", ride.get("id"), scrub_log_text(exc))
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to delete ride storage object",
            ) from None
    return deleted


async def check_ride_access(
    ride: dict,
    current_user: Optional[AuthenticatedUser],
    level: str = "read",
    repo: Optional[DatabaseRepository] = None,
) -> VisibilityDecision:
    """
    Check if current_user can access a ride.

    Levels:
      - "owner": only the ride owner (for PATCH, DELETE, reprocess, download)
      - "read": owner OR visibility allows it (for GET endpoints)

    Raises HTTPException(403) or HTTPException(404) on failure.
    """
    decision = await resolve_ride_visibility(ride, current_user, repo=repo)
    if decision.is_owner:
        return decision
    if level == "owner":
        raise HTTPException(status_code=403, detail="Not your ride")
    if decision.can_view:
        return decision
    raise HTTPException(status_code=404, detail="Ride not found")


@router.get("", response_model=list[RideRecord])
async def list_rides(
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    limit: int = Query(50, ge=1, le=100),
    offset: int = Query(0, ge=0),
) -> list[RideRecord]:
    rides = await ride_repo.list_rides_for_user(
        current_user.user_id,
        limit=limit,
        offset=offset,
    )
    threshold_projections = await _threshold_ride_projections_for_owner(
        ride_repo, rides
    )
    rides = [
        _project_threshold_ride_for_client(
            row,
            threshold_projections[str(row.get("id"))],
        )
        if str(row.get("id")) in threshold_projections
        else row
        for row in rides
    ]
    rides = await _project_threshold_training_for_owner(
        ride_repo,
        current_user.user_id,
        rides,
    )
    media_by_ride = await _serialized_ride_media_for_rides(
        ride_repo,
        [str(row.get("id")) for row in rides if row.get("id")],
    )
    counted_steps = await ride_repo.list_counted_climb_steps(rides)
    records: list[RideRecord] = []
    for row in rides:
        decision = await resolve_ride_visibility(row, current_user, repo=ride_repo)
        privacy = decision.to_client_dict()
        stored_points = _decode_ride_gps_points(row)
        preview_points, preview_zones = await _project_route_for_viewer(
            row, stored_points, decision, ride_repo,
        )
        row_for_record = {
            **row,
            "_route_preview_points": preview_points,
            "_route_preview_zones": preview_zones,
            "_list_shape": build_ride_list_shape(
                row, stored_points, counted_steps.get(str(row.get("id")), []),
            ) if decision.is_owner else {},
        }
        media = media_by_ride.get(str(row.get("id")), [])
        record = _to_ride_record(row_for_record, privacy=privacy, media=media)
        # Upload time is an owner-list fact, not part of the shared detail projection.
        if decision.is_owner:
            record.uploaded_at = _parse_datetime(row.get("uploaded_at"))
        records.append(record)
    return records


@router.get("/{ride_id}")
async def get_ride(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Get a single ride by ID."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    decision = await check_ride_access(ride, current_user, level="read", repo=repo)
    is_owner = decision.is_owner

    # Fetch vault completions for this ride from chain-indexed tables
    vault_completions = []
    try:
        # indexed_completions is per user+vault (aggregated), not per activity.
        # We match via patterns_climb entries for this ride.
        patterns = ride.get("patterns") or []
        vault_sigs = []
        for p in patterns:
            if isinstance(p, dict) and p.get("vault_signature"):
                vault_sigs.append(p["vault_signature"])
        if vault_sigs:
            vaults_result = repo.client.table("indexed_vaults") \
                .select("id,name,signature_hex") \
                .in_("signature_hex", vault_sigs) \
                .execute()
            for v in (vaults_result.data or []):
                # Get best_time from indexed_completions for this user+vault
                wallet = ride.get("wallet") or ride.get("user_wallet")
                ic_result = repo.client.table("indexed_completions") \
                    .select("best_time_s") \
                    .eq("user_pubkey", wallet) \
                    .eq("vault_id", v["id"]) \
                    .execute()
                best_time = None
                if ic_result.data:
                    best_time = ic_result.data[0].get("best_time_s")
                vault_completions.append({
                    "vault_id": v["id"],
                    "vault_name": v["name"],
                    "vault_signature": v["signature_hex"],
                    "time_seconds": best_time,
                })
    except Exception as e:
        logger.warning(f"[GetRide] Failed to fetch vault completions: {e}")

    if is_owner and current_user is not None:
        projections = await _threshold_ride_projections_for_owner(repo, [ride])
        if ride_id in projections:
            ride = _project_threshold_ride_for_client(ride, projections[ride_id])
        ride = (
            await _project_threshold_training_for_owner(
                repo,
                current_user.user_id,
                [ride],
            )
        )[0]
    else:
        ride = _withhold_private_threshold_economy(ride)
    privacy = decision.to_client_dict()
    media = await _serialized_ride_media(repo, ride_id)
    preview_points, preview_zones = await _route_preview_points_for_record(
        ride,
        decision,
        repo,
    )
    release_resolution = _fetch_terminal_threshold_release_authority(
        repo, ride_id, ride
    )
    row_for_record = {
        **ride,
        "_threshold_release_status": _client_threshold_release_status(
            release_resolution[0]
        ),
        "_route_preview_points": preview_points,
        "_route_preview_zones": preview_zones,
    }
    ride_record = _to_ride_record(
        row_for_record,
        vault_completions,
        privacy=privacy,
        media=media,
        cal_itemization=(
            _fetch_ride_cal_itemization(repo, ride_id, ride, release_resolution)
            if _threshold_economy_visible(ride)
            and ride.get("threshold_economy_state") in {None, "counted"}
            else None
        ),
    )
    # Return frontend aliases (durationS, elevationM, calories, etc.) for detail views.
    return {**_serialize_ride_record(ride_record, is_owner=is_owner), "is_owner": is_owner}


async def _ride_interactions_for_detail(
    repo: DatabaseRepository,
    ride_id: str,
    ride: dict[str, Any],
    current_user: Optional[AuthenticatedUser],
) -> dict[str, Any]:
    get_summaries = getattr(repo, "get_interaction_summaries", None)
    summaries = await get_summaries(
        "ride",
        [ride_id],
        current_user.user_id if current_user else None,
    ) if get_summaries else {}
    summary = summaries.get(ride_id, {})
    return {
        "rideId": ride_id,
        "kudosCount": summary.get("kudosCount", 0),
        "commentCount": summary.get("commentCount", 0),
        "viewerHasKudos": summary.get("viewerHasKudos", False),
        "viewerReported": summary.get("viewerReported", False),
        "reportStatus": summary.get("reportStatus"),
        "commentsEnabled": ride.get("comments_enabled", True) is not False,
        "canComment": (ride.get("comments_enabled", True) is not False) and current_user is not None,
    }


async def _ride_comments_for_detail(
    repo: DatabaseRepository,
    ride_id: str,
    current_user: Optional[AuthenticatedUser],
    limit: int,
) -> dict[str, Any]:
    try:
        from .interactions import _comment_author, _with_signed_comment_avatar

        comments = await repo.get_comments("ride", ride_id)
        get_report_summaries = getattr(repo, "get_report_summaries", None)
        if current_user and get_report_summaries and comments:
            summaries = await get_report_summaries(
                "comment",
                [str(comment.get("id")) for comment in comments if comment.get("id")],
                current_user.user_id,
            )
            for comment in comments:
                comment.update(summaries.get(str(comment.get("id")), {}))
        enriched = []
        for comment in comments[:limit]:
            comment.update(await _with_signed_comment_avatar(comment, current_user))
            comment["author"] = _comment_author(comment)
            enriched.append(comment)
        return {
            "comments": enriched,
            "count": len(comments),
            "hasMore": len(comments) > limit,
        }
    except Exception as exc:
        logger.debug("[RideDetail] Comment preview unavailable for %s: %s", ride_id, exc)
        return {"comments": [], "count": 0, "hasMore": False}


@router.get("/{ride_id}/detail")
async def get_ride_detail(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    user_repo: UserRepository = Depends(get_user_repository),
    comments_limit: int = Query(20, ge=0, le=50),
):
    """One first-paint ride detail contract for mobile and portal detail views."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    decision = await check_ride_access(ride, current_user, level="read", repo=repo)
    if decision.is_owner and current_user is not None:
        projections = await _threshold_ride_projections_for_owner(repo, [ride])
        if ride_id in projections:
            ride = _project_threshold_ride_for_client(ride, projections[ride_id])
        ride = (
            await _project_threshold_training_for_owner(
                repo,
                current_user.user_id,
                [ride],
            )
        )[0]
    else:
        ride = _withhold_private_threshold_economy(ride)
    privacy = decision.to_client_dict()
    media = await _serialized_ride_media(repo, ride_id)
    preview_points, preview_zones = await _route_preview_points_for_record(
        ride,
        decision,
        repo,
    )
    release_resolution = _fetch_terminal_threshold_release_authority(
        repo, ride_id, ride
    )
    ride = {
        **ride,
        "_threshold_release_status": _client_threshold_release_status(
            release_resolution[0]
        ),
    }
    row_for_record = {
        **ride,
        "_route_preview_points": preview_points,
        "_route_preview_zones": preview_zones,
    }
    ride_record = _to_ride_record(
        row_for_record,
        privacy=privacy,
        media=media,
        cal_itemization=(
            _fetch_ride_cal_itemization(repo, ride_id, ride, release_resolution)
            if _threshold_economy_visible(ride)
            and ride.get("threshold_economy_state") in {None, "counted"}
            else None
        ),
    )

    processing_status = str(ride.get("processing_status") or "pending")
    climb_earnings = (
        _fetch_ride_climb_earnings_for_client(
            repo, ride_id, ride, release_resolution
        )
        if processing_status in CLIMB_EARNING_READY_STATUSES
        else []
    )
    if not decision.is_owner:
        climb_earnings = _withhold_climb_economy(climb_earnings)
    status_response = _build_ride_status_response(
        ride_id,
        ride,
        climb_earnings,
        include_economy=decision.is_owner,
    )

    from .links import _resolve_link
    from ..link_contracts import LinkTargetType

    interactions, comments, resolved_link = await asyncio.gather(
        _ride_interactions_for_detail(repo, ride_id, ride, current_user),
        _ride_comments_for_detail(repo, ride_id, current_user, comments_limit),
        _resolve_link(LinkTargetType.ride, ride_id, repo, current_user),
    )

    # The ride's rider, privacy-projected (private profiles keep name and
    # avatar withheld by the shared ref helper) — every ride page leads
    # with its athlete, like the feed already does.
    rider_row = None
    try:
        owner_id = ride.get("user_id")
        if owner_id:
            rider_row = await user_repo.get_user_by_id(str(owner_id))
    except Exception:
        rider_row = None
    from ..rider_identity_contracts import public_rider_ref_dict
    rider_ref = public_rider_ref_dict(rider_row, fallback_id=ride.get("user_id"))

    return {
        "contractVersion": "ride_detail.v1",
        "ride": {
            **_serialize_ride_record(
                ride_record,
                is_owner=decision.is_owner,
                mode="json",
            ),
            "isOwner": current_user is not None and ride.get("user_id") == current_user.user_id,
        },
        "rider": rider_ref,
        "status": status_response,
        "interactions": interactions,
        "comments": comments,
        "link": resolved_link,
        "freshness": {
            "source": "backend",
            "loadedAt": datetime.now(timezone.utc).isoformat(),
            "status": processing_status,
        },
    }


@router.get("/{ride_id}/original")
async def get_ride_original(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Return a short-lived owner-only URL for the exact uploaded ride file."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="owner", repo=repo)

    storage_path = str(ride.get("raw_file_path") or "").strip()
    if not storage_path:
        raise HTTPException(
            status_code=404,
            detail="Original ride file is not available",
        )

    raw_type = str(ride.get("file_type") or "").strip().lower()
    path_extension = storage_path.rsplit(".", 1)[-1].lower() if "." in storage_path else ""
    file_type = raw_type if raw_type in {"fit", "gpx", "tcx"} else path_extension
    if file_type not in {"fit", "gpx", "tcx"}:
        file_type = "bin"

    supplied_name = str(ride.get("file_name") or "").replace("\\", "/")
    file_name = posixpath.basename(supplied_name).strip()
    if not file_name or file_name in {".", ".."}:
        file_name = f"Ride.{file_type}"

    mime_types = {
        "fit": "application/vnd.ant.fit",
        "gpx": "application/gpx+xml",
        "tcx": "application/vnd.garmin.tcx+xml",
        "bin": "application/octet-stream",
    }
    storage = create_file_storage_service()
    try:
        signed_url = await storage.get_signed_url(
            storage_path,
            expires_in=SIGNED_URL_EXPIRY_SECONDS,
        )
    except StorageUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Original ride file is temporarily unavailable",
        ) from exc

    return {
        "signedUrl": signed_url,
        "fileName": file_name,
        "fileType": file_type,
        "mimeType": mime_types[file_type],
        "expiresIn": SIGNED_URL_EXPIRY_SECONDS,
    }


@router.post("/upload", response_model=RideUploadResponse)
@rate_limit(category="ride_upload")
async def upload_ride(
    http_request: Request,
    ride_request: RideUploadRequest,
    force: bool = Query(False, description="Skip duplicate check (dev only)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> RideUploadResponse:
    """
    Upload a ride file for processing.

    Legacy inline upload fallback.
    1. Decode and store raw file to Supabase Storage FIRST
    2. Check for duplicates via file hash
    3. Create ride record with storage path
    4. Enqueue the canonical ride-processing job

    Query params:
        force: Skip duplicate check (useful during development)
    """
    _reject_public_force_upload(force)

    # 1. Decode base64 to raw bytes
    try:
        file_bytes = base64.b64decode(ride_request.file_data_b64)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid base64 encoding: {exc}",
        )

    # 2. Initialize storage service and compute file hash
    storage = create_file_storage_service()
    file_hash = storage.compute_file_hash(file_bytes)

    # 3. Check for duplicate (same user, same file hash)
    if not force:
        existing = await _find_blocking_upload_duplicate(
            ride_repo,
            current_user.user_id,
            file_hash,
            context="RideUpload",
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_upload_duplicate_detail(existing),
            )

    privacy_policy = await _resolve_write_privacy_policy(
        ride_repo,
        current_user.user_id,
        ride_request,
    )

    # 4. Generate ride ID upfront (needed for storage path)
    ride_id = str(uuid_module.uuid4())

    # 5. Upload to Supabase Storage
    try:
        storage_result = await storage.upload_ride_file(
            user_id=current_user.user_id,
            ride_id=ride_id,
            file_bytes=file_bytes,
            file_type=ride_request.file_type,
        )
        logger.info(
            f"[RideUpload] Stored file: path={storage_result.path}, "
            f"size={storage_result.size_bytes}, hash={storage_result.file_hash[:16]}..."
        )
    except FileTooLargeError as exc:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=str(exc),
        )
    except StorageUnavailableError as exc:
        logger.error(f"[RideUpload] Storage unavailable: {exc}")
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage temporarily unavailable. Please retry.",
        )

    # 6. Create ride record WITH storage metadata
    import_diagnostics = _upload_import_diagnostics(
        preliminary_ride_hash=ride_request.preliminary_ride_hash,
        parser_version=ride_request.parser_version,
    )
    await ride_repo.create_ride(
        user_id=current_user.user_id,
        ride_id=ride_id,
        status="processing",
        file_type=ride_request.file_type,
        raw_file_path=storage_result.path,
        raw_file_size_bytes=storage_result.size_bytes,
        file_hash=storage_result.file_hash,
        upload_verified_at=datetime.now(timezone.utc),
        preliminary_ride_hash_hex=(
            ride_request.preliminary_ride_hash.lower()
            if ride_request.preliminary_ride_hash
            else None
        ),
        preliminary_parser_version=ride_request.parser_version,
        import_diagnostics=import_diagnostics,
        privacy_policy=privacy_policy,
    )

    # 7. Get user profile for processing params
    profile = await user_repo.get_user_profile(current_user.wallet)
    user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

    status_value = "processing"
    message = "Ride uploaded. Processing in background."
    enqueue_status = "queued"

    enqueue_result = await enqueue_ride_ingest(
        RideIngestJob(
            ride_id=ride_id,
            wallet=current_user.wallet,
            user_id=str(current_user.user_id),
            file_type=ride_request.file_type,
            file_path=storage_result.path,
            user_weight_kg=user_weight,
            source="manual_upload_inline",
        )
    )
    if not enqueue_result.accepted:
        await ride_repo.update_ride_status(
            UUID(ride_id),
            "pending",
            error_message=enqueue_result.error,
        )
        status_value = "pending"
        message = "Ride uploaded but ingest queue unavailable; will retry."
        enqueue_status = "queue_failed"
    elif enqueue_result.backend == "celery_fallback":
        message = "Ride uploaded. Processing queued via fallback."
        enqueue_status = "queued_fallback"

    KPI_RIDE_UPLOADS.labels(status=enqueue_status).inc()

    return RideUploadResponse(
        ride_id=UUID(ride_id),
        status=status_value,
        message=message,
    )


# ---------- Presigned Upload Flow ----------
# Three-phase upload: init → client PUT to storage → complete/abort

ALLOWED_FILE_TYPES = {"fit", "gpx", "tcx"}
SIGNED_URL_EXPIRY_SECONDS = 600  # 10 minutes


def _stable_upload_detail(
    existing: dict[str, Any],
    *,
    error: str,
    message: str,
) -> dict[str, Any]:
    return {
        "error": error,
        "message": message,
        "existing_ride_id": str(existing.get("id") or ""),
        "existing_status": str(existing.get("processing_status") or "unknown"),
    }


def _normalized_client_completed_at(value: Optional[datetime]) -> Optional[str]:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    else:
        value = value.astimezone(timezone.utc)
    return value.isoformat()


def _stable_upload_matches_request(
    existing: dict[str, Any],
    init_request: UploadInitRequest,
    *,
    user_id: str,
    upload_id: str,
    file_type: str,
) -> bool:
    """Compare one stable retry with the immutable inputs already on its ride row."""
    expected_path = f"rides/{user_id}/{upload_id}.{file_type}"
    scalar_pairs = (
        (str(existing.get("file_type") or "").lower().strip("."), file_type),
        (str(existing.get("file_hash") or "").lower(), init_request.file_hash.lower()),
        (existing.get("raw_file_size_bytes"), init_request.file_size),
        (str(existing.get("raw_file_path") or ""), expected_path),
        (
            str(existing.get("preliminary_ride_hash_hex") or "").lower() or None,
            init_request.preliminary_ride_hash.lower()
            if init_request.preliminary_ride_hash
            else None,
        ),
        (existing.get("preliminary_parser_version"), init_request.parser_version),
    )
    if any(actual != expected for actual, expected in scalar_pairs):
        return False

    diagnostics = existing.get("import_diagnostics")
    stored_completed_at = (
        diagnostics.get("client_completed_at")
        if isinstance(diagnostics, dict)
        else None
    )
    if stored_completed_at != _normalized_client_completed_at(init_request.client_completed_at):
        return False

    explicit_privacy = {
        "visibility": init_request.visibility,
        "map_visibility": init_request.map_visibility,
        "map_hide_start_m": init_request.map_hide_start_m,
        "map_hide_end_m": init_request.map_hide_end_m,
    }
    return all(
        expected is None or existing.get(field) == expected
        for field, expected in explicit_privacy.items()
    )


async def _resume_stable_upload(
    *,
    existing: dict[str, Any],
    init_request: UploadInitRequest,
    current_user: AuthenticatedUser,
    file_type: str,
) -> UploadInitResponse:
    upload_id = str(init_request.client_request_id)
    user_id = str(current_user.user_id)
    if str(existing.get("user_id") or "") != user_id:
        # A caller-provided UUID must not disclose another rider's upload.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    if not _stable_upload_matches_request(
        existing,
        init_request,
        user_id=user_id,
        upload_id=upload_id,
        file_type=file_type,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_stable_upload_detail(
                existing,
                error="upload_request_mismatch",
                message="This upload ID is already bound to different file inputs.",
            ),
        )

    current_status = str(existing.get("processing_status") or "unknown")
    if current_status != "uploading":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_stable_upload_detail(
                existing,
                error="upload_already_initialized",
                message="This upload has already moved beyond file transfer.",
            ),
        )

    storage_path = str(existing["raw_file_path"])
    storage = create_file_storage_service()
    try:
        signed_result = await storage.create_signed_upload_url(storage_path)
    except StorageUnavailableError as exc:
        # The durable uploading row is the retry token. Do not invalidate it
        # merely because one signed-URL attempt could not reach storage.
        logger.error(
            "[UploadInit] Storage unavailable while reissuing stable upload %s: %s",
            upload_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage temporarily unavailable. Please retry.",
        ) from exc

    return UploadInitResponse(
        upload_id=upload_id,
        signed_url=signed_result["signed_url"],
        expires_in=SIGNED_URL_EXPIRY_SECONDS,
    )


@router.post("/upload/init", response_model=UploadInitResponse)
@rate_limit(category="ride_upload")
async def upload_init(
    http_request: Request,
    init_request: UploadInitRequest,
    force: bool = Query(False, description="Skip duplicate check (dev only)"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UploadInitResponse:
    """
    Initiate a presigned upload.

    Returns a signed URL that the client uses to PUT the file directly
    to Supabase Storage, bypassing the API server for file transfer.

    Flow: init → client PUTs to signed_url → complete
    """
    _reject_public_force_upload(force)

    # 1. Validate file type
    file_type = init_request.file_type.lower().strip(".")
    if file_type not in ALLOWED_FILE_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type '{init_request.file_type}'. Allowed: {', '.join(sorted(ALLOWED_FILE_TYPES))}",
        )

    stable_upload_id = (
        str(init_request.client_request_id)
        if init_request.client_request_id is not None
        else None
    )
    if stable_upload_id is not None:
        existing_stable_upload = await ride_repo.get_ride(stable_upload_id)
        if existing_stable_upload:
            return await _resume_stable_upload(
                existing=existing_stable_upload,
                init_request=init_request,
                current_user=current_user,
                file_type=file_type,
            )

    # 2. Check for duplicate (same user, same file hash)
    if not force:
        existing = await _find_blocking_upload_duplicate(
            ride_repo,
            current_user.user_id,
            init_request.file_hash,
            context="UploadInit",
        )
        if existing:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=_upload_duplicate_detail(existing),
            )

    privacy_policy = await _resolve_write_privacy_policy(
        ride_repo,
        current_user.user_id,
        init_request,
    )

    # 3. Generate ride/upload ID and create ride row in "uploading" state
    ride_id = stable_upload_id or str(uuid_module.uuid4())
    storage_path = f"rides/{current_user.user_id}/{ride_id}.{file_type}"
    import_diagnostics: Optional[dict[str, Any]] = None
    if init_request.client_completed_at is not None:
        client_completed_at = init_request.client_completed_at
        if client_completed_at.tzinfo is None:
            client_completed_at = client_completed_at.replace(tzinfo=timezone.utc)
        else:
            client_completed_at = client_completed_at.astimezone(timezone.utc)
        pre_economy_activity = is_pre_economy_activity(client_completed_at)
        import_diagnostics = {
            "client_completed_at": client_completed_at.isoformat(),
            "pre_economy_activity": pre_economy_activity,
            "economy_review_reason": (
                PRE_ECONOMY_REVIEW_REASON if pre_economy_activity else None
            ),
        }
    import_diagnostics = _upload_import_diagnostics(
        preliminary_ride_hash=init_request.preliminary_ride_hash,
        parser_version=init_request.parser_version,
        base=import_diagnostics,
    )

    try:
        await ride_repo.create_ride(
            user_id=current_user.user_id,
            ride_id=ride_id,
            status="uploading",
            file_type=file_type,
            raw_file_path=storage_path,
            raw_file_size_bytes=init_request.file_size,
            file_hash=init_request.file_hash,
            preliminary_ride_hash_hex=init_request.preliminary_ride_hash.lower() if init_request.preliminary_ride_hash else None,
            preliminary_parser_version=init_request.parser_version,
            import_diagnostics=import_diagnostics,
            privacy_policy=privacy_policy,
        )
    except Exception:
        # Concurrent first attempts with one client UUID race on the ride PK.
        # Resolve the winner as the same stable retry; unrelated create errors
        # retain their original failure instead of being hidden.
        if stable_upload_id is None:
            raise
        concurrent_upload = await ride_repo.get_ride(stable_upload_id)
        if not concurrent_upload:
            raise
        return await _resume_stable_upload(
            existing=concurrent_upload,
            init_request=init_request,
            current_user=current_user,
            file_type=file_type,
        )

    # 4. Generate signed upload URL from Supabase Storage
    storage = create_file_storage_service()
    try:
        signed_result = await storage.create_signed_upload_url(storage_path)
    except StorageUnavailableError as exc:
        if stable_upload_id is None:
            # Legacy clients cannot address this random row again, so retain
            # the prior failed-row behavior for duplicate cleanup.
            logger.error(f"[UploadInit] Storage unavailable, cleaning up ride {ride_id}: {exc}")
            try:
                await ride_repo.update_ride_status(UUID(ride_id), "failed", error_message="Storage unavailable")
            except Exception:
                pass
        else:
            logger.error(
                "[UploadInit] Storage unavailable; stable upload %s remains retryable: %s",
                ride_id,
                exc,
            )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="File storage temporarily unavailable. Please retry.",
        )

    logger.info(
        f"[UploadInit] Created upload {ride_id} for user {current_user.user_id}, "
        f"path=[redacted], size={init_request.file_size}"
    )

    return UploadInitResponse(
        upload_id=ride_id,
        signed_url=signed_result["signed_url"],
        expires_in=SIGNED_URL_EXPIRY_SECONDS,
    )


@router.post("/upload/complete", response_model=UploadCompleteResponse)
@rate_limit(category="ride_upload")
async def upload_complete(
    http_request: Request,
    complete_request: UploadCompleteRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    user_repo: UserRepository = Depends(get_user_repository),
) -> UploadCompleteResponse:
    """
    Finalize a presigned upload.

    Called after the client has successfully PUT the file to the signed URL.
    Verifies the file exists in storage, updates the ride status, and queues
    the processing job.
    """
    upload_id = complete_request.upload_id

    # 1. Fetch the ride row
    ride = await ride_repo.get_ride(upload_id)
    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # 2. Verify ownership
    if str(ride.get("user_id") or "") != str(current_user.user_id):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # 3. Completed processing states are read-only replays. Pending is the
    # durable queue handoff state and must rebuild the same job after a crash
    # or queue outage.
    current_status = str(ride.get("processing_status") or "unknown")
    if current_status not in {"uploading", "pending"}:
        return UploadCompleteResponse(
            ride_id=upload_id,
            status=current_status,
        )

    # 4. Both uploading verification and pending replay need the immutable
    # storage identity used to rebuild the ingest job.
    storage_path = ride.get("raw_file_path")
    if not storage_path:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Upload record missing storage path",
        )

    if current_status == "uploading":
        storage = create_file_storage_service()
        file_exists = await storage.file_exists(storage_path)
        if not file_exists:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "error": "file_missing",
                    "message": "File not found in storage. Upload may have failed or expired.",
                },
            )

        # 5. Verify file size if we can.
        declared_size = ride.get("raw_file_size_bytes")
        if declared_size:
            actual_size = await storage.get_file_size(storage_path)
            if actual_size is not None and actual_size != declared_size:
                logger.warning(
                    f"[UploadComplete] Size mismatch for {upload_id}: "
                    f"declared={declared_size}, actual={actual_size}"
                )
                # Allow small discrepancies due to storage overhead, but reject large ones.
                if actual_size > declared_size * 1.1 or actual_size < declared_size * 0.5:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail="File size does not match declared size",
                    )

        # 6. Verify content hash from the uploaded object, not the declaration.
        hash_verify_started = time.perf_counter()
        try:
            uploaded_bytes = await storage.download_ride_file(storage_path)
        except Exception as exc:
            logger.error(
                "[UploadComplete] Failed to download uploaded object %s: %s",
                "[redacted]",
                scrub_log_text(exc),
            )
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Unable to verify uploaded file",
            ) from exc

        expected_hash = str(ride.get("file_hash") or "").lower()
        actual_hash = storage.compute_file_hash(uploaded_bytes).lower()
        hash_verify_ms = int((time.perf_counter() - hash_verify_started) * 1000)
        log_hash_verification = (
            logger.warning
            if hash_verify_ms >= UPLOAD_COMPLETE_HASH_WARN_MS
            else logger.info
        )
        log_hash_verification(
            "[UploadComplete] Verified uploaded object hash for %s in %sms (bytes=%s)",
            upload_id,
            hash_verify_ms,
            len(uploaded_bytes),
        )
        if expected_hash and actual_hash != expected_hash:
            logger.warning(
                "[UploadComplete] Hash mismatch for %s: declared=%s actual=%s",
                upload_id,
                expected_hash,
                actual_hash,
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="File hash does not match uploaded content",
            )

        # Verification becomes durable before any operation that can suspend,
        # crash, or fail while preparing the queue job.
        transitioned = await ride_repo.transition_ride_status(
            UUID(upload_id),
            expected_status="uploading",
            new_status="pending",
            upload_verified_at=datetime.now(timezone.utc).isoformat(),
        )
        if not transitioned:
            refreshed = await ride_repo.get_ride(upload_id)
            if not refreshed or str(refreshed.get("user_id") or "") != str(
                current_user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Upload not found",
                )
            refreshed_status = str(refreshed.get("processing_status") or "unknown")
            if refreshed_status != "pending":
                return UploadCompleteResponse(
                    ride_id=upload_id,
                    status=refreshed_status,
                )
            ride = refreshed
            storage_path = ride.get("raw_file_path")
            if not storage_path:
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail="Upload record missing storage path",
                )

    # 7. Pending replay deterministically rebuilds the same ride-id job.
    profile = await user_repo.get_user_profile(current_user.wallet)
    user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

    enqueue_result = await enqueue_ride_ingest(
        RideIngestJob(
            ride_id=upload_id,
            wallet=current_user.wallet,
            user_id=str(current_user.user_id),
            file_type=ride.get("file_type", "fit"),
            file_path=storage_path,
            user_weight_kg=user_weight,
            source="manual_upload_direct",
        )
    )
    status_value = "pending"
    upload_metric_status = "queue_failed"
    if not enqueue_result.accepted:
        transitioned = await ride_repo.transition_ride_status(
            UUID(upload_id),
            expected_status="pending",
            new_status="pending",
            error_message=enqueue_result.error,
        )
        if not transitioned:
            refreshed = await ride_repo.get_ride(upload_id)
            if not refreshed or str(refreshed.get("user_id") or "") != str(
                current_user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Upload not found",
                )
            status_value = str(refreshed.get("processing_status") or "unknown")
    else:
        transitioned = await ride_repo.transition_ride_status(
            UUID(upload_id),
            expected_status="pending",
            new_status="processing",
        )
        if transitioned:
            status_value = "processing"
        else:
            refreshed = await ride_repo.get_ride(upload_id)
            if not refreshed or str(refreshed.get("user_id") or "") != str(
                current_user.user_id
            ):
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail="Upload not found",
                )
            status_value = str(refreshed.get("processing_status") or "unknown")
        upload_metric_status = (
            "queued_fallback"
            if enqueue_result.backend == "celery_fallback"
            else "queued"
        )

    KPI_RIDE_UPLOADS.labels(status=upload_metric_status).inc()

    return UploadCompleteResponse(
        ride_id=upload_id,
        status=status_value,
    )


@router.post("/upload/abort", response_model=UploadAbortResponse)
@rate_limit(category="ride_upload")
async def upload_abort(
    http_request: Request,
    abort_request: UploadAbortRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> UploadAbortResponse:
    """
    Abort a presigned upload.

    Cleans up the storage file (if partially uploaded) and marks the ride
    record as aborted.
    """
    upload_id = abort_request.upload_id

    # 1. Fetch the ride row
    ride = await ride_repo.get_ride(upload_id)
    if not ride:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Upload not found",
        )

    # 2. Verify ownership
    if ride.get("user_id") != current_user.user_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Not your upload",
        )

    # 3. Only allow aborting uploads in "uploading" state
    current_status = ride.get("processing_status")
    if current_status != "uploading":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Upload is in '{current_status}' state, can only abort 'uploading'",
        )

    # 4. Delete file from storage if present
    storage_path = ride.get("raw_file_path")
    if storage_path:
        storage = create_file_storage_service()
        try:
            await storage.delete_ride_file(storage_path)
            logger.info(f"[UploadAbort] Deleted storage file [redacted]")
        except Exception as exc:
            logger.warning(f"[UploadAbort] Failed to delete storage file [redacted]: {scrub_log_text(exc)}")

    # 5. Mark ride as failed/aborted
    await ride_repo.update_ride_status(
        UUID(upload_id), "failed", error_message="Upload aborted by user"
    )

    logger.info(f"[UploadAbort] Aborted upload {upload_id} for user {current_user.user_id}")

    return UploadAbortResponse(status="aborted")


@router.patch("/{ride_id}")
async def update_ride(
    ride_id: str,
    update_request: RideUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Update ride metadata (title, description, visibility, etc.)."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="owner")

    # Build update dict from non-None fields
    updates = {}
    if update_request.title is not None:
        # Rider edits land on rides.title; file_name stays the original
        # upload filename. An empty/whitespace edit clears back to NULL so
        # the default-title fallback shape returns.
        updates["title"] = update_request.title.strip() or None
    if update_request.description is not None:
        updates["description"] = update_request.description
    if update_request.activity_type is not None:
        updates["activity_type"] = update_request.activity_type
    if any(
        value is not None
        for value in (
            update_request.visibility,
            update_request.map_visibility,
            update_request.map_hide_start_m,
            update_request.map_hide_end_m,
        )
    ):
        try:
            privacy_policy = _resolve_ride_privacy_edit(ride, update_request)
        except PrivacySettingsUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Ride privacy is temporarily unavailable. Please retry.",
            ) from exc
        updates.update(privacy_policy.to_storage_dict())
    if update_request.comments_enabled is not None:
        updates["comments_enabled"] = update_request.comments_enabled
    if update_request.hide_from_leaderboards is not None:
        updates["hide_from_leaderboards"] = update_request.hide_from_leaderboards
    if "perceived_exertion" in update_request.model_fields_set:
        updates["perceived_exertion"] = update_request.perceived_exertion

    if updates:
        await repo.update_ride_metadata(ride_id, updates)

    return {"status": "updated", "ride_id": ride_id}


@router.get("/{ride_id}/media", response_model=list[RideMedia])
async def list_ride_media(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """List persisted media for a ride the viewer can access."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    decision = await check_ride_access(ride, current_user, level="read", repo=repo)
    return await _serialized_ride_media(repo, ride_id)


@router.post("/{ride_id}/media/init", response_model=RideMediaInitResponse)
@rate_limit(category="ride_upload")
async def ride_media_upload_init(
    http_request: Request,
    ride_id: str,
    init_request: RideMediaInitRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> RideMediaInitResponse:
    """Create a signed upload URL for a ride photo."""
    ride = await ride_repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    mime_type = _normalize_media_mime_type(init_request.mime_type)
    if mime_type not in ALLOWED_RIDE_MEDIA_MIME_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Ride media must be a JPEG, PNG, WebP, HEIC, or HEIF image.",
        )

    stable_media_id = (
        str(init_request.client_request_id)
        if init_request.client_request_id is not None
        else None
    )
    if stable_media_id is not None:
        existing = await ride_repo.get_ride_media(stable_media_id)
        if existing:
            if (
                str(existing.get("ride_id") or "") != ride_id
                or str(existing.get("user_id") or "") != str(current_user.user_id)
            ):
                raise HTTPException(status_code=404, detail="Ride media not found")
            expected_path = (
                f"ride-media/{current_user.user_id}/{ride_id}/{stable_media_id}."
                f"{_media_extension(mime_type, init_request.file_name)}"
            )
            exact_retry = all((
                str(existing.get("storage_path") or "") == expected_path,
                existing.get("file_name") == init_request.file_name,
                str(existing.get("mime_type") or "") == mime_type,
                int(existing.get("size_bytes") or 0) == init_request.file_size,
                int(existing.get("sort_order") or 0)
                    == int(init_request.sort_order or 0),
                str(existing.get("role") or "photo") == init_request.role,
                str(existing.get("upload_status") or "uploading") == "uploading",
            ))
            if not exact_retry:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="This photo ID is already bound to different inputs.",
                )
            storage = create_file_storage_service()
            try:
                signed_result = await storage.create_signed_upload_url(expected_path)
            except StorageUnavailableError as exc:
                raise HTTPException(
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                    detail="Photo storage temporarily unavailable. Please retry.",
                ) from exc
            return RideMediaInitResponse(
                media_id=stable_media_id,
                signed_url=signed_result["signed_url"],
                expires_in=SIGNED_URL_EXPIRY_SECONDS,
            )

    existing_media = []
    list_media = getattr(ride_repo, "list_ride_media", None)
    if list_media:
        existing_media = await list_media(ride_id, include_uploading=True)
    active_media = [
        row for row in existing_media
        if str(row.get("upload_status") or "ready") != "failed"
        and str(row.get("moderation_state") or "visible") not in {"hidden", "removed"}
    ]
    if len(active_media) >= MAX_RIDE_MEDIA_PER_RIDE:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Rides can have up to {MAX_RIDE_MEDIA_PER_RIDE} photos.",
        )

    media_id = stable_media_id or str(uuid_module.uuid4())
    sort_order = init_request.sort_order if init_request.sort_order is not None else len(active_media)
    ext = _media_extension(mime_type, init_request.file_name)
    storage_path = f"ride-media/{current_user.user_id}/{ride_id}/{media_id}.{ext}"

    storage = create_file_storage_service()
    try:
        signed_result = await storage.create_signed_upload_url(storage_path)
    except StorageUnavailableError as exc:
        logger.error("[RideMediaInit] Storage unavailable for ride %s: %s", ride_id, exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Photo storage temporarily unavailable. Please retry.",
        ) from exc

    await ride_repo.create_ride_media(
        media_id=media_id,
        ride_id=ride_id,
        user_id=current_user.user_id,
        storage_path=storage_path,
        file_name=init_request.file_name,
        mime_type=mime_type,
        size_bytes=init_request.file_size,
        sort_order=sort_order,
        role=init_request.role,
    )

    return RideMediaInitResponse(
        media_id=media_id,
        signed_url=signed_result["signed_url"],
        expires_in=SIGNED_URL_EXPIRY_SECONDS,
    )


@router.post("/{ride_id}/media/complete", response_model=RideMedia)
@rate_limit(category="ride_upload")
async def ride_media_upload_complete(
    http_request: Request,
    ride_id: str,
    complete_request: RideMediaCompleteRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> RideMedia:
    """Finalize a direct-to-storage ride photo upload."""
    media = await ride_repo.get_ride_media(complete_request.media_id)
    if not media or str(media.get("ride_id")) != ride_id:
        raise HTTPException(status_code=404, detail="Media upload not found")
    if media.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride media")
    if str(media.get("upload_status") or "uploading") != "uploading":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Media upload is already {media.get('upload_status')}",
        )

    storage_path = media.get("storage_path")
    if not storage_path:
        await ride_repo.mark_ride_media_failed(complete_request.media_id)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Media upload missing storage path",
        )

    storage = create_file_storage_service()
    try:
        photo = await storage.prepare_photo(storage_path, media["mime_type"], int(media.get("size_bytes") or 0))
    except StorageFileNotFoundError:
        raise HTTPException(status_code=400, detail="Photo not found in storage. Upload may have failed or expired.") from None
    except InvalidPhotoError as exc:
        logger.warning("Ride photo rejected reason=%s exit_code=%s", exc.reason, exc.exit_code)
        raise HTTPException(status_code=400, detail="Media upload could not be completed") from None
    except StorageUnavailableError:
        raise HTTPException(status_code=503, detail="Photo storage temporarily unavailable. Please retry.") from None

    ready = await ride_repo.complete_ride_media_upload(
        complete_request.media_id,
        ride_id=ride_id,
        storage_path=photo.path,
        size_bytes=photo.size_bytes,
        mime_type=photo.mime_type,
        width=photo.width,
        height=photo.height,
    )
    if not ready:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Media upload could not be completed",
        )
    return await serialize_ride_media(ready or media, storage=storage)


@router.patch("/{ride_id}/media/reorder", response_model=list[RideMedia])
async def reorder_ride_media(
    ride_id: str,
    reorder_request: RideMediaReorderRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> list[RideMedia]:
    """Reorder a ride's photos for owner-managed display."""
    ride = await ride_repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    if ride.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=403, detail="Not your ride")

    if not reorder_request.items:
        return await _serialized_ride_media(ride_repo, ride_id)

    known_media = await ride_repo.list_ride_media(ride_id, include_uploading=True)
    known_ids = {
        str(row.get("id"))
        for row in known_media
        if row.get("user_id") == current_user.user_id
    }
    order = {
        str(item.media_id): int(item.sort_order)
        for item in reorder_request.items
    }
    if not set(order).issubset(known_ids):
        raise HTTPException(status_code=404, detail="One or more ride photos were not found")

    rows = await ride_repo.reorder_ride_media(ride_id, order)
    return await serialize_ride_media_list(rows)


@router.patch("/{ride_id}/media/{media_id}", response_model=RideMedia)
async def update_ride_media(
    ride_id: str,
    media_id: str,
    update_request: RideMediaUpdateRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> RideMedia:
    """Update owner-managed ride photo fields like cover and order."""
    media = await _require_owned_ride_media(
        ride_repo,
        ride_id=ride_id,
        media_id=media_id,
        current_user=current_user,
    )

    updated: Optional[dict] = None
    if update_request.role == "cover":
        if str(media.get("upload_status") or "") != "ready":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Photo is not ready")
        if str(media.get("moderation_state") or "visible") != "visible":
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Photo is not visible")
        updated = await ride_repo.set_ride_media_cover(ride_id=ride_id, media_id=media_id)
    else:
        updates: dict[str, Any] = {}
        if update_request.role is not None:
            updates["role"] = update_request.role
        if update_request.sort_order is not None:
            updates["sort_order"] = update_request.sort_order
        updated = await ride_repo.update_ride_media(media_id, updates)

    if not updated:
        raise HTTPException(status_code=404, detail="Ride media not found")
    return await serialize_ride_media(updated)


@router.delete("/{ride_id}/media/{media_id}")
async def delete_ride_media(
    ride_id: str,
    media_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
):
    """Delete one persisted ride photo."""
    media = await _require_owned_ride_media(
        ride_repo,
        ride_id=ride_id,
        media_id=media_id,
        current_user=current_user,
    )

    storage_path = media.get("storage_path")
    if storage_path:
        storage = create_file_storage_service()
        try:
            await storage.delete_photo_files(storage_path)
        except StorageUnavailableError:
            raise HTTPException(status_code=503, detail="Photo storage temporarily unavailable. Please retry.") from None
    was_cover = str(media.get("role") or "") == "cover"
    await ride_repo.delete_ride_media(media_id)
    if was_cover:
        remaining_media = await ride_repo.list_ride_media(ride_id)
        next_cover = next((row for row in remaining_media if str(row.get("id")) != media_id), None)
        if next_cover:
            await ride_repo.set_ride_media_cover(
                ride_id=ride_id,
                media_id=str(next_cover.get("id")),
            )
    return {"status": "deleted", "mediaId": media_id}


@router.get("/{ride_id}/status")
async def get_ride_status(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get ride processing status with progressive data based on phase.

    Status progression:
    - pending: Ride uploaded, waiting for processing
    - processing: Phase 1 in progress (parsing, metrics)
    - metrics_ready: Phase 1 complete - basic metrics available
    - enriched: Phase 2 complete - patterns and leaderboards available
    - completed: Phase 3 complete - all data including rewards available
    - under_review: canonical mismatch detected; ride stored but not auto-attested
    - failed: Processing failed (check error_message)
    """
    ride = await repo.get_ride(ride_id)

    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")

    decision = await check_ride_access(ride, current_user, level="read", repo=repo)
    if decision.is_owner and current_user is not None:
        projections = await _threshold_ride_projections_for_owner(repo, [ride])
        if ride_id in projections:
            ride = _project_threshold_ride_for_client(ride, projections[ride_id])
        ride = (
            await _project_threshold_training_for_owner(
                repo,
                current_user.user_id,
                [ride],
            )
        )[0]
    else:
        ride = _withhold_private_threshold_economy(ride)

    release_resolution = _fetch_terminal_threshold_release_authority(
        repo, ride_id, ride
    )
    ride = {
        **ride,
        "_threshold_release_status": _client_threshold_release_status(
            release_resolution[0]
        ),
    }
    processing_status = str(ride.get("processing_status") or "pending")
    climb_earnings = (
        _fetch_ride_climb_earnings_for_client(
            repo, ride_id, ride, release_resolution
        )
        if processing_status in CLIMB_EARNING_READY_STATUSES
        else []
    )
    if not decision.is_owner:
        climb_earnings = _withhold_climb_economy(climb_earnings)
    return _build_ride_status_response(
        ride_id,
        ride,
        climb_earnings,
        include_economy=decision.is_owner,
    )


@router.get("/{ride_id}/training")
@rate_limit(category="analytics")
async def get_ride_training(ride_id: str, request: Request,
    start_s: Optional[int] = Query(None, ge=0), end_s: Optional[int] = Query(None, ge=0),
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository)):
    ride = await repo.get_ride(ride_id)
    if not ride: raise HTTPException(404, "Ride not found")
    await check_ride_access(ride, current_user, level="owner", repo=repo)
    if not is_training_eligible(ride):
        return None
    if start_s is None and end_s is None:
        return ride.get("training_metrics")
    if start_s is None or end_s is None or end_s <= start_s:
        raise HTTPException(422, "invalid training span")
    if not ride.get("training_inputs") or not ride.get("raw_file_path"):
        raise HTTPException(409, "training evidence unavailable")
    from ..services.training_activity_cache import activity_for_span
    from ..services.training_metrics import compute
    activity = await activity_for_span(ride, current_user.user_id)
    return await asyncio.to_thread(compute, activity, ride["training_inputs"], start_s=start_s, end_s=end_s)


@router.get("/{ride_id}/streams")
async def get_ride_streams(
    ride_id: str,
    type: str = Query(..., description="Stream type: power, heart_rate, cadence, speed, temperature"),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    decision = await check_ride_access(ride, current_user, level="read", repo=repo)

    # Public/follower ride detail may be viewable, but exact sensor samples are
    # owner-only.
    if not decision.is_owner:
        return _empty_ride_stream_response(ride_id, type, redacted=True)

    # Use raw ride_id to support legacy non-UUID activity identifiers.
    stream = await repo.get_activity_stream(ride_id, type)
    if not stream:
        # Return empty stream data instead of 404
        # This prevents console errors on frontend when stream doesn't exist
        return _empty_ride_stream_response(ride_id, type)
    return stream


@router.get("/{ride_id}/gps")
async def get_ride_gps(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)

    # Use raw ride_id to support legacy non-UUID activity identifiers.
    points = await repo.get_gps_track(ride_id)

    # Attach the DEM-corrected relief projection before privacy trimming so
    # corrected values stay aligned with whichever points survive.
    points = _attach_corrected_elevation(ride, points)

    # Public/follower detail may be viewable while exact telemetry remains private.
    decision = await resolve_ride_visibility(ride, current_user, repo=repo)
    points, _zones = await _project_route_for_viewer(ride, points, decision, repo)
    if not decision.is_owner:
        # Hidden points leave the API without elevation or time.
        points = strip_hidden_point_details(points)

    return {"gps_points": points}


@router.get("/{ride_id}/patterns")
async def get_ride_patterns(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get detected patterns for a ride.

    Returns all patterns detected during ride processing:
    - climb_patterns: Sustained climbing efforts
    - steady_pattern: Z2-Z3 aerobic blocks
    - exploration_pattern: New tile discovery
    """
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)
    decision = await resolve_ride_visibility(ride, current_user, repo=repo)

    # Use raw ride_id to support legacy non-UUID activity identifiers.
    patterns = await repo.get_patterns_for_activity(ride_id)
    try:
        owner = await repo.get_user_by_id(str(ride["user_id"]))
    except Exception:
        owner = None  # Unavailable account/preferences never grant visibility.
    try:
        powers = await pattern_power(ClimbEffortRepository(repo.client), ride,
                                     patterns.get("climb_patterns") or [], current_user, rider=owner)
    except Exception as exc:
        # An unavailable authority must not revive legacy power; the climbs
        # stay readable and every power field is dropped below.
        logger.warning("Pattern power unavailable for ride %s: %s", ride_id, scrub_log_text(exc))
        powers = {}

    # Real vault-match facts (this ride's completion truth) keyed by pattern id.
    vault_matches = _fetch_pattern_vault_matches(repo, ride_id, ride)

    # Enrich climb patterns with computed fields
    if patterns.get("climb_patterns"):
        for climb in patterns["climb_patterns"]:
            from ..services.climb_read_metrics import climb_category
            climb["category"] = climb_category(climb.get("distance_m"), climb.get("avg_gradient_pct"))
            for field in ClimbPatternPower.model_fields:
                climb.pop(field, None)
            climb.update(powers.get(str(climb.get("id")), {}))
            # Canon registry climbId wherever the authoritative pattern→canon
            # binding exists, independent of completion state — this is the
            # climb-sheet deep-link key for pattern-only rides. Authority
            # only; detector-era rows get nothing. (boulderroller-v2-nrbu5)
            canon_registry_id = authoritative_canon_climb_id(climb)
            if canon_registry_id:
                climb["climbId"] = canon_registry_id
            vert_m = climb.get("vert_m", 0)
            time_s = climb.get("time_s", 0)
            # Add duration_s alias (frontend expects this name)
            climb["duration_s"] = time_s
            # Compute VAM (vertical ascent meters per hour)
            if time_s > 0:
                climb["vam"] = round(vert_m / time_s * 3600, 1)
            else:
                climb["vam"] = 0
            # Use road_name if available, otherwise generate placeholder
            if climb.get("road_name"):
                climb["name"] = climb["road_name"]
            elif not climb.get("name"):
                climb["name"] = f"Climb ({vert_m:.1f}m)"
            # Convert snake_case to camelCase for frontend
            if "tile_ids" in climb:
                climb["tileIds"] = climb.pop("tile_ids")
            if "start_offset_s" in climb:
                climb["startOffsetS"] = climb.pop("start_offset_s")
            if "end_offset_s" in climb:
                climb["endOffsetS"] = climb.pop("end_offset_s")
            if "start_time_offset_s" in climb:
                climb["startTimeOffsetS"] = climb.pop("start_time_offset_s")
            if "end_time_offset_s" in climb:
                climb["endTimeOffsetS"] = climb.pop("end_time_offset_s")
            if "distance_m" in climb:
                climb["distanceM"] = climb.pop("distance_m")
            if "avg_gradient_pct" in climb:
                climb["avgGradientPct"] = climb.pop("avg_gradient_pct")
            if "avg_speed_mps" in climb:
                climb["avgSpeedMps"] = climb.pop("avg_speed_mps")
            if "signature_hex" in climb:
                climb["signatureHex"] = climb.pop("signature_hex")
            if "road_name" in climb:
                climb["roadName"] = climb.pop("road_name")
            if "persistence_m" in climb:
                climb["persistenceM"] = climb.pop("persistence_m")
            if "significance_g" in climb:
                climb["significanceG"] = climb.pop("significance_g")
            if "significance_percentile" in climb:
                climb["significancePercentile"] = climb.pop("significance_percentile")
            if "significance_return_period" in climb:
                climb["significanceReturnPeriod"] = climb.pop("significance_return_period")
            if "significance_confidence_tier" in climb:
                climb["significanceConfidenceTier"] = climb.pop("significance_confidence_tier")
            if "significance_bootstrapped" in climb:
                climb["significanceBootstrapped"] = climb.pop("significance_bootstrapped")
            if "vault_match" in climb:
                climb["vaultMatch"] = climb.pop("vault_match")
            # Attach real completion-backed vault-match facts for this ride.
            real_match = vault_matches.get(str(climb.get("id")))
            if real_match is not None:
                climb["vaultMatch"] = real_match

    if decision.redact_gps:
        patterns = _redact_pattern_route_fields(patterns)
    # W/kg (from the training read above or the stored patterns_climb column)
    # and the steady pattern's intensity_index stop here for everyone but the
    # ride's owner.
    if getattr(decision, "is_owner", False) is not True:
        share_wkg = isinstance(owner, dict) and owner.get("share_wkg") is True
        patterns = _withhold_owner_only_pattern_fields(patterns, share_wkg=share_wkg)

    # Calculate summary
    summary_parts = []
    if patterns.get("climb_patterns"):
        total_vert = sum(p.get("vert_m", 0) for p in patterns["climb_patterns"])
        summary_parts.append(f"{int(total_vert)}m climbed")
    if patterns.get("steady_pattern"):
        mins = patterns["steady_pattern"].get("duration_s", 0) // 60
        summary_parts.append(f"{mins}min steady")
    if patterns.get("exploration_pattern"):
        new_tiles = patterns["exploration_pattern"].get("new_tiles_wallet", 0)
        summary_parts.append(f"{new_tiles} new areas explored")

    return {
        "ride_id": ride_id,
        "patterns": patterns,
        "summary": ", ".join(summary_parts) if summary_parts else "No patterns detected",
        "total_count": (
            len(patterns.get("climb_patterns", []))
            + (1 if patterns.get("steady_pattern") else 0)
            + (1 if patterns.get("exploration_pattern") else 0)
        ),
    }


@router.delete("/{ride_id}")
async def delete_ride(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """Delete a ride and all associated data."""
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="owner")

    deleted_storage_count = await _delete_ride_storage_objects(ride, repo)
    await repo.delete_ride(ride_id)
    logger.info(
        "[Rides] Deleted ride %s for user %s and removed %d storage object(s)",
        ride_id,
        current_user.user_id,
        deleted_storage_count,
    )
    return {"status": "deleted", "ride_id": ride_id}


@router.post("/{ride_id}/reprocess")
async def reprocess_ride(
    ride_id: str,
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    user_repo: UserRepository = Depends(get_user_repository),
):
    """
    Re-queue a ride for processing from its stored file.

    Useful for:
    - Retrying failed rides without re-upload
    - Re-processing after algorithm improvements

    Only works for rides with stored files (raw_file_path).
    """
    ride = await ride_repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="owner")

    # Check if file was stored
    raw_file_path = ride.get("raw_file_path")
    if not raw_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot reprocess: original file not stored. This ride was uploaded before file storage was enabled.",
        )

    # Reset status and increment reprocess count
    await ride_repo.update_ride_status(UUID(ride_id), "processing")
    await ride_repo.clear_ride_error(ride_id)
    await ride_repo.increment_reprocess_count(ride_id)

    # Get user profile for processing params
    profile = await user_repo.get_user_profile(current_user.wallet)
    user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0

    enqueue_result = await enqueue_ride_ingest(
        RideIngestJob(
            ride_id=ride_id,
            wallet=current_user.wallet,
            user_id=str(current_user.user_id),
            file_type=ride.get("file_type", "fit"),
            file_path=raw_file_path,
            user_weight_kg=user_weight,
            source="ride_reprocess",
            reprocess=True,
        )
    )
    if not enqueue_result.accepted:
        await ride_repo.update_ride_status(
            UUID(ride_id),
            "pending",
            error_message=enqueue_result.error,
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Processing queue unavailable. Please retry.",
        )

    return {
        "status": "reprocessing",
        "ride_id": ride_id,
        "message": "Ride queued for reprocessing",
    }


@router.post("/cleanup-stale")
async def cleanup_stale_rides(
    admin: bool = Query(False, description="Admin mode: clean up all users' stale rides"),
    current_user: AuthenticatedUser = Depends(get_current_user),
    ride_repo: RideRepository = Depends(get_ride_repository),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Clean up rides stuck in processing states.

    Handles:
    - 'processing' or 'pending' status for >1 hour
    - 'metrics_ready' stuck >30 minutes without Phase 2 completion

    By default only cleans up the current user's rides.
    Pass admin=true to clean up all users' stale rides (admin only, requires admin role).

    Returns:
        count: Number of stale rides cleaned up
        ride_ids: List of affected ride IDs
    """
    from datetime import timedelta

    # Admin mode requires admin role — prevent privilege escalation
    if admin:
        from .admin import require_admin
        from ..compliance_repository import ComplianceRepository
        compliance = ComplianceRepository()
        role = await compliance.get_admin_role(UUID(current_user.user_id))
        if not role:
            raise HTTPException(status_code=403, detail="Admin access required")

    one_hour_ago = datetime.now(timezone.utc) - timedelta(hours=1)
    thirty_min_ago = datetime.now(timezone.utc) - timedelta(minutes=30)

    cleaned_up = []

    # Case 1: processing/pending stuck >1 hour
    query = ride_repo._client.table("rides") \
        .select("id,created_at,user_id") \
        .in_("processing_status", ["processing", "pending"]) \
        .lt("created_at", one_hour_ago.isoformat())

    if not admin:
        query = query.eq("user_id", current_user.user_id)

    result = query.execute()
    stale_rides = result.data or []

    for ride in stale_rides:
        ride_id = ride["id"]
        await ride_repo.update_ride_status(
            UUID(ride_id),
            "failed",
            error_message="Processing timed out. Please try re-uploading the file.",
        )
        cleaned_up.append(ride_id)
        logger.info(f"[CleanupStale] Marked ride {ride_id} as failed (processing timeout)")

    # Case 2: metrics_ready stuck >30 minutes
    query2 = ride_repo._client.table("rides") \
        .select("id,phase1_completed_at,user_id") \
        .eq("processing_status", "metrics_ready") \
        .is_("phase2_completed_at", "null") \
        .lt("phase1_completed_at", thirty_min_ago.isoformat())

    if not admin:
        query2 = query2.eq("user_id", current_user.user_id)

    result2 = query2.execute()
    stale_metrics = result2.data or []

    for ride in stale_metrics:
        ride_id = ride["id"]
        await ride_repo.update_ride_status(
            UUID(ride_id),
            "failed",
            error_message="Enrichment timed out. Please try re-uploading the file.",
        )
        cleaned_up.append(ride_id)
        logger.info(f"[CleanupStale] Marked ride {ride_id} as failed (metrics_ready timeout)")

    return {
        "status": "cleaned",
        "count": len(cleaned_up),
        "ride_ids": cleaned_up,
    }


@router.get("/{ride_id}/tiles")
async def get_ride_tiles(
    ride_id: str,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get tile samples for a ride.

    Returns H3 tile sequence with associated metrics.
    Useful for map visualization and pattern analysis.
    """
    ride = await repo.get_ride(ride_id)
    if not ride:
        raise HTTPException(status_code=404, detail="Ride not found")
    await check_ride_access(ride, current_user, level="read", repo=repo)
    decision = await resolve_ride_visibility(ride, current_user, repo=repo)
    if decision.redact_gps:
        return {
            "ride_id": ride_id,
            "tile_samples": [],
            "total_samples": 0,
            "unique_tiles": 0,
            "redacted": True,
        }

    # Query tile samples - paginate to overcome Supabase 1000 row default limit
    # Large rides (8+ hours) can have 20,000+ samples
    all_data = []
    page_size = 1000
    pages = PageCursor(page_size)

    while True:
        response = await repo._run(
            lambda offset=pages.offset: order_by(
                repo._client.table("activity_tile_samples")
                .select("tile_id, t, elevation_m, power_w, hr_bpm, speed_mps")
                .eq("activity_id", ride_id),
                "t",
                "id",
            )
            .range(offset, offset + page_size - 1)
            .execute()
        )
        page_data = getattr(response, "data", None) or []
        all_data.extend(page_data)
        # range() is end-exclusive here; the cursor advances by what arrived.
        if not pages.advance(page_data):
            logger.debug(f"[TileFetch] ride={ride_id} done after {pages.pages} pages: {len(all_data)} rows")
            break

        # Safety limit to prevent infinite loops (50k samples = ~14 hour ride)
        if pages.offset > 50000:
            logger.warning(f"[TileFetch] Safety limit at offset {pages.offset}. Total: {len(all_data)}")
            break

    data = all_data

    # Get unique tile count
    unique_tiles = set(row["tile_id"] for row in data)

    return {
        "ride_id": ride_id,
        "tile_samples": data,
        "total_samples": len(data),
        "unique_tiles": len(unique_tiles),
    }
