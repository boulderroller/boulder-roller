"""Freeze one immutable held-ride release from provisional evidence."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import math
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import UUID, uuid4

from ..repositories.ride_economic import (
    RideEconomicRepository,
    ThresholdReleaseAuthorityConflictError,
)
from .cal_tribute_policy import (
    CAL_TRIBUTE_POWER_METRICS_VERSION,
    MIN_SEGMENT_POWER_COVERAGE_BPS,
    MIN_SEGMENT_POWER_SAMPLE_COUNT,
    calculate_intensity_bps,
    calculate_ride_tribute_budget,
    calculate_segment_tss_base_units,
)
from .ride_economic_plan import CompletionStepDraft
from .threshold_release_executor import ThresholdReleaseExecutor
from .reward_ftp import RewardFtpSnapshot
from .reward_threshold import (
    THRESHOLD_PROVISIONAL_HOLD_POLICY,
    build_held_ride_release_policy,
)
from .workout_parse_adapter import calculate_threshold_release_tss


THRESHOLD_HOLD_EVIDENCE_VERSION = 2
THRESHOLD_RELEASE_PLAN_DOMAIN = "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V2"


def _source_value(source: Any, name: str) -> Any:
    return source.get(name) if isinstance(source, Mapping) else getattr(source, name, None)


def _utc_datetime(value: Any, *, field: str) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise ValueError(f"{field} must be an ISO datetime") from exc
    else:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be a timezone-aware datetime")
    return parsed.astimezone(timezone.utc)


def _utc_iso(value: Any, *, field: str) -> str:
    return _utc_datetime(value, field=field).isoformat()


def _required_int(value: Any, *, field: str, minimum: int = 0) -> int:
    if isinstance(value, bool):
        raise ValueError(f"{field} must be an exact integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be an exact integer") from exc
    if isinstance(value, float) and value != parsed:
        raise ValueError(f"{field} must be an exact integer")
    if parsed < minimum:
        raise ValueError(f"{field} must be at least {minimum}")
    return parsed


def _optional_number(value: Any, *, field: str) -> Optional[float]:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not math.isfinite(parsed):
        raise ValueError(f"{field} must be finite")
    return parsed


def build_threshold_hold_evidence(
    *,
    metrics: Any,
    completion_steps: Sequence[CompletionStepDraft],
    effort_trim=None,
    started_at: Any = None,
    completed_at: Any = None,
) -> dict[str, Any]:
    """Retain only the inputs needed to price a provisional ride once.

    The 200 W placeholder's TSS, CAL, intensity, and V2 receipt hashes are
    deliberately excluded. Those paying fields are derived only after a real
    Threshold authority exists.
    """
    normalized_power = _optional_number(
        _source_value(metrics, "normalized_power_raw_w"),
        field="normalized_power_raw_w",
    )
    if normalized_power is None or normalized_power <= 0:
        raise ValueError("provisional hold requires positive raw normalized power")
    duration_s = _required_int(
        _source_value(metrics, "normalized_power_duration_s"),
        field="normalized_power_duration_s",
        minimum=1,
    )
    started = started_at if started_at is not None else _source_value(metrics, "started_at")
    completed = (
        completed_at if completed_at is not None else _source_value(metrics, "completed_at")
    )
    metric_evidence = {
        "normalized_power_raw_w": normalized_power,
        "normalized_power_duration_s": duration_s,
        "normalized_power_w": _optional_number(
            _source_value(metrics, "normalized_power_w"),
            field="normalized_power_w",
        ),
        "avg_power_w": _optional_number(
            _source_value(metrics, "avg_power_w"), field="avg_power_w"
        ),
        "avg_hr_bpm": _optional_number(
            _source_value(metrics, "avg_hr_bpm"), field="avg_hr_bpm"
        ),
        "metrics_version": str(_source_value(metrics, "metrics_version") or ""),
        "moving_time_sec": _required_int(
            _source_value(metrics, "moving_time_sec"),
            field="moving_time_sec",
        ),
        "duration_sec": _required_int(
            _source_value(metrics, "duration_sec"), field="duration_sec", minimum=1
        ),
        "power_sample_count": _required_int(
            _source_value(metrics, "power_sample_count"),
            field="power_sample_count",
        ),
        "power_sample_coverage_bps": _required_int(
            _source_value(metrics, "power_sample_coverage_bps"),
            field="power_sample_coverage_bps",
        ),
        "heart_rate_sample_count": _required_int(
            _source_value(metrics, "heart_rate_sample_count") or 0,
            field="heart_rate_sample_count",
        ),
        "heart_rate_sample_coverage_bps": _required_int(
            _source_value(metrics, "heart_rate_sample_coverage_bps") or 0,
            field="heart_rate_sample_coverage_bps",
        ),
        "started_at": _utc_iso(started, field="started_at"),
        "completed_at": _utc_iso(completed, field="completed_at"),
    }

    provisional_steps: list[dict[str, Any]] = []
    seen_vaults: set[int] = set()
    for step in sorted(completion_steps, key=lambda value: (value.vault_id, str(value.pattern_id))):
        # Vault ids come from the on-chain VaultCounter, which starts at 0
        # (Shawmont Avenue is Vault 0); every other validator allows u64 zero.
        vault_id = _required_int(step.vault_id, field="vault_id", minimum=0)
        if vault_id in seen_vaults:
            raise ValueError(f"duplicate provisional completion vault {vault_id}")
        seen_vaults.add(vault_id)
        completion_time_s = _required_int(
            step.completion_time_s, field="completion_time_s", minimum=1
        )
        segment_np_w = (
            _required_int(step.segment_np_w, field="segment_np_w")
            if step.segment_np_w is not None
            else None
        )
        segment_np_milliwatts = (
            _required_int(
                step.segment_np_milliwatts,
                field="segment_np_milliwatts",
            )
            if step.segment_np_milliwatts is not None
            else None
        )
        segment_np_duration_s = _required_int(
            step.segment_np_duration_s,
            field="segment_np_duration_s",
        )
        tribute_weight = _required_int(
            step.tribute_weight, field="tribute_weight"
        )
        if tribute_weight != 0:
            raise ValueError("provisional measured-TSS steps cannot use weights")
        if (segment_np_w is None) != (segment_np_milliwatts is None):
            raise ValueError("provisional rounded and exact segment NP must agree")
        if segment_np_milliwatts is not None and segment_np_duration_s == 0:
            raise ValueError("provisional segment NP requires a positive duration")
        if (
            segment_np_milliwatts is not None
            and segment_np_w != (segment_np_milliwatts + 500) // 1_000
        ):
            raise ValueError("provisional rounded segment NP is not canonical")
        segment_start_offset_s = _required_int(
            step.segment_start_offset_s, field="segment_start_offset_s"
        )
        segment_end_offset_s = _required_int(
            step.segment_end_offset_s, field="segment_end_offset_s"
        )
        if segment_end_offset_s < segment_start_offset_s:
            raise ValueError("segment end offset cannot precede its start")
        # Inclusive whole-second window: completion_time + 1 samples, ±1 for rounding.
        window_samples = segment_end_offset_s - segment_start_offset_s + 1
        if segment_np_duration_s > window_samples:
            raise ValueError("NP duration exceeds climb window")
        if window_samples > completion_time_s + 2:
            raise ValueError("segment window does not match completion time")
        provisional_steps.append(
            {
                "pattern_id": str(step.pattern_id),
                "vault_id": vault_id,
                "vault_signature": str(step.vault_signature),
                "completion_time_s": completion_time_s,
                "completed_at": _utc_iso(step.completed_at, field="completed_at"),
                "segment_start_offset_s": segment_start_offset_s,
                "segment_end_offset_s": segment_end_offset_s,
                "segment_np_w": segment_np_w,
                "segment_np_milliwatts": segment_np_milliwatts,
                "segment_np_duration_s": segment_np_duration_s,
                "segment_power_sample_count": _required_int(
                    step.segment_power_sample_count,
                    field="segment_power_sample_count",
                ),
                "segment_power_coverage_bps": _required_int(
                    step.segment_power_coverage_bps,
                    field="segment_power_coverage_bps",
                ),
                "segment_power_metrics_version": str(
                    step.segment_power_metrics_version
                ),
                "tribute_weight": tribute_weight,
                "climb_distance_m": step.climb_distance_m,
                "climb_vert_m": step.climb_vert_m,
            }
        )
    for row in provisional_steps:
        if (
            row["segment_power_sample_count"] < MIN_SEGMENT_POWER_SAMPLE_COUNT
            or row["segment_power_coverage_bps"]
            < MIN_SEGMENT_POWER_COVERAGE_BPS
        ) and row["segment_np_milliwatts"] is not None:
            raise ValueError("insufficient segment power cannot authorize tribute")
    by_window = sorted(
        provisional_steps,
        key=lambda row: (
            row["segment_start_offset_s"],
            row["segment_end_offset_s"],
        ),
    )
    for previous, current in zip(by_window, by_window[1:]):
        if current["segment_start_offset_s"] <= previous["segment_end_offset_s"]:
            raise ValueError("overlapping eligible climb windows require review")
    return {
        **({"effort_trim": effort_trim.payload(include_metrics=False)} if effort_trim is not None else {}),
        "version": THRESHOLD_HOLD_EVIDENCE_VERSION,
        "metrics": metric_evidence,
        "completion_steps": provisional_steps,
    }


@dataclass(frozen=True)
class ThresholdReleasePlanningOutcome:
    status: str
    durable_checkpoint: bool
    snapshot_id: Optional[str] = None
    error: Optional[str] = None


class _TerminalReleaseDisposition(ValueError):
    def __init__(self, disposition: str, reason: str) -> None:
        self.disposition = disposition
        super().__init__(reason)


class ThresholdReleasePlanner:
    """Claim one eligible hold and freeze its release-specific authority."""

    def __init__(
        self,
        *,
        repository: RideEconomicRepository,
        executor: ThresholdReleaseExecutor,
        lease_seconds: int = 300,
        lease_owner_factory: Callable[[], UUID] = uuid4,
    ) -> None:
        self.repository = repository
        self.executor = executor
        self.lease_seconds = max(1, int(lease_seconds))
        self._lease_owner_factory = lease_owner_factory

    async def run_once(self) -> ThresholdReleasePlanningOutcome:
        lease_owner = self._lease_owner_factory()
        claim = await self.repository.claim_due_threshold_release_item(
            lease_owner=lease_owner,
            lease_seconds=self.lease_seconds,
        )
        if claim is None:
            return ThresholdReleasePlanningOutcome(
                status="idle", durable_checkpoint=True
            )
        try:
            snapshot, steps = self._build_snapshot(claim)
        except (KeyError, TypeError, ValueError) as exc:
            return await self._mark_terminal_claim(
                claim=claim,
                lease_owner=lease_owner,
                error=exc,
            )

        # Persistence failures are retryable. They must not turn a valid,
        # already-claimed ride into a permanent review disposition merely
        # because the database was temporarily unavailable.
        try:
            frozen = await self.repository.freeze_threshold_release_snapshot(
                snapshot=snapshot,
                steps=steps,
                lease_owner=lease_owner,
            )
        except ThresholdReleaseAuthorityConflictError as exc:
            if exc.code != "BRR07":
                raise
            return await self._mark_terminal_claim(
                claim=claim,
                lease_owner=lease_owner,
                error=exc,
            )
        return ThresholdReleasePlanningOutcome(
            status="planned",
            durable_checkpoint=True,
            snapshot_id=str(frozen.get("snapshot_id") or frozen.get("id")),
        )

    async def _mark_terminal_claim(
        self,
        *,
        claim: Mapping[str, Any],
        lease_owner: UUID,
        error: Exception,
    ) -> ThresholdReleasePlanningOutcome:
        terminal = getattr(
            self.repository, "mark_threshold_release_item_terminal", None
        )
        if not callable(terminal):
            raise error
        disposition = (
            error.disposition
            if isinstance(error, _TerminalReleaseDisposition)
            else "review"
        )
        await terminal(
            batch_item_id=UUID(str(claim["batch_item_id"])),
            lease_owner=lease_owner,
            disposition=disposition,
            reason=str(error),
            evidence={
                "version": 1,
                "hold_evidence_hash_hex": claim.get("hold_evidence_hash_hex"),
                "admission_plan_evidence_hash_hex": claim.get(
                    "admission_plan_evidence_hash_hex"
                ),
                "error_type": type(error).__name__,
            },
        )
        return ThresholdReleasePlanningOutcome(
            status="review",
            durable_checkpoint=True,
            error=str(error),
        )

    def _build_snapshot(
        self, claim: Mapping[str, Any]
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        evidence = claim.get("hold_evidence")
        if not isinstance(evidence, Mapping):
            raise ValueError("release claim lacks frozen hold evidence")
        if int(evidence.get("version") or 0) != THRESHOLD_HOLD_EVIDENCE_VERSION:
            raise ValueError("unsupported Threshold hold evidence version")
        metrics = evidence.get("metrics")
        if not isinstance(metrics, Mapping):
            raise ValueError("release claim lacks frozen power metrics")

        admitted_at = _utc_datetime(claim.get("admitted_at"), field="admitted_at")
        established_at = _utc_datetime(
            claim.get("established_at"), field="established_at"
        )
        threshold = RewardFtpSnapshot.from_row(
            {
                "reward_ftp_w": claim.get("reward_ftp_w"),
                "reward_ftp_source": claim.get("reward_ftp_source"),
                "reward_ftp_authority_id": claim.get("reward_ftp_authority_id"),
                "reward_ftp_policy_version": claim.get(
                    "reward_ftp_policy_version"
                ),
            }
        )
        release_tss = calculate_threshold_release_tss(
            normalized_power_raw_w=float(metrics["normalized_power_raw_w"]),
            normalized_power_duration_s=int(metrics["normalized_power_duration_s"]),
            threshold_w=threshold.ftp_w,
        )
        release_metrics = dict(metrics)
        release_metrics["tss"] = release_tss
        release_metrics["normalized_power_w"] = float(
            metrics["normalized_power_raw_w"]
        )
        policy = build_held_ride_release_policy(
            release_metrics,
            admitted_at=admitted_at,
            established_at=established_at,
            established_threshold=threshold,
        )
        if policy.disposition != "release":
            raise _TerminalReleaseDisposition(
                (
                    "not_counted"
                    if policy.disposition == "not_counted"
                    else "review"
                ),
                f"held ride is not releasable: {policy.disposition}"
                + (f" ({policy.review_reason})" if policy.review_reason else ""),
            )

        wallet = str(claim.get("wallet") or "")
        if not wallet:
            raise ValueError("release claim lacks rider wallet")
        try:
            ride_hash = bytes.fromhex(str(claim["ride_hash_hex"]))
        except (KeyError, ValueError) as exc:
            raise ValueError("release claim lacks a valid ride hash") from exc
        if len(ride_hash) != 32:
            raise ValueError("release ride hash must be 32 bytes")

        release_pda = self.executor.derive_held_ride_release_pda(
            rider_wallet=wallet,
            ride_hash=ride_hash,
        )
        cal_receipt_pda = self.executor.derive_cal_receipt_pda(
            rider_wallet=wallet,
            ride_hash=ride_hash,
        )
        raw_steps = evidence.get("completion_steps") or []
        if not isinstance(raw_steps, list):
            raise ValueError("provisional completion evidence must be an array")
        allocations = [
            calculate_segment_tss_base_units(
                segment_np_duration_s=int(row["segment_np_duration_s"]),
                segment_np_milliwatts=(
                    int(row["segment_np_milliwatts"])
                    if row.get("segment_np_milliwatts") is not None
                    else None
                ),
                reward_ftp_w=threshold.ftp_w,
            )
            for row in raw_steps
        ]
        exact_tribute_budget_base_units = calculate_ride_tribute_budget(
            policy.exact_cal_base_units,
            allocations,
        )

        steps: list[dict[str, Any]] = []
        for step_index, (row, tribute) in enumerate(zip(raw_steps, allocations)):
            vault_id = int(row["vault_id"])
            completion_time_s = int(row["completion_time_s"])
            segment_np_w = row.get("segment_np_w")
            evidence_hash = self.executor.build_released_completion_evidence_v3(
                rider_wallet=wallet,
                ride_hash=ride_hash,
                vault_id=vault_id,
                completion_time_s=completion_time_s,
                cal_tribute=tribute,
                expected_release_authority_pda=release_pda,
            )
            if len(evidence_hash) != 32:
                raise ValueError("released completion evidence hash must be 32 bytes")
            steps.append(
                {
                    "step_index": step_index,
                    "pattern_id": str(row["pattern_id"]),
                    "vault_id": vault_id,
                    "vault_signature": str(row["vault_signature"]),
                    "completion_time_s": completion_time_s,
                    "completed_at": _utc_iso(
                        row["completed_at"], field="completion_completed_at"
                    ),
                    "exact_tribute_base_units": tribute,
                    "intensity_bps": calculate_intensity_bps(
                        segment_np_milliwatts=(
                            int(row["segment_np_milliwatts"])
                            if row.get("segment_np_milliwatts") is not None
                            else None
                        ),
                        reward_ftp_w=threshold.ftp_w,
                    ),
                    "segment_start_offset_s": int(row["segment_start_offset_s"]),
                    "segment_end_offset_s": int(row["segment_end_offset_s"]),
                    "segment_np_w": segment_np_w,
                    "segment_np_milliwatts": row.get("segment_np_milliwatts"),
                    "segment_np_duration_s": int(row["segment_np_duration_s"]),
                    "segment_power_sample_count": int(
                        row["segment_power_sample_count"]
                    ),
                    "segment_power_coverage_bps": int(
                        row["segment_power_coverage_bps"]
                    ),
                    "segment_power_metrics_version": str(
                        row.get("segment_power_metrics_version")
                        or CAL_TRIBUTE_POWER_METRICS_VERSION
                    ),
                    "tribute_weight": int(row["tribute_weight"]),
                    "climb_distance_m": row.get("climb_distance_m"),
                    "climb_vert_m": row.get("climb_vert_m"),
                    "completion_evidence_version": 3,
                    "completion_evidence_hash_hex": evidence_hash.hex(),
                    "expected_receipt_pda": (
                        self.executor.derive_completion_receipt_pda(
                            rider_wallet=wallet,
                            ride_hash=ride_hash,
                            vault_id=vault_id,
                        )
                    ),
                }
            )

        plan = {
            "batch_item_id": str(claim["batch_item_id"]),
            "ride_id": str(claim["ride_id"]),
            "user_id": str(claim["user_id"]),
            "wallet": wallet,
            "ride_hash_hex": ride_hash.hex(),
            "admitted_at": admitted_at.isoformat(),
            "established_at": established_at.isoformat(),
            "reward_ftp_authority_id": str(threshold.authority_id),
            "reward_ftp_authority_evidence_hash_hex": str(
                claim["reward_ftp_authority_evidence_hash_hex"]
            ).lower(),
            "reward_ftp_w": threshold.ftp_w,
            "reward_ftp_source": threshold.source,
            "reward_ftp_policy_version": threshold.policy_version,
            "economic_tss": policy.economic_tss,
            "total_tss": int(policy.economic_tss),
            "exact_cal_base_units": policy.exact_cal_base_units,
            "exact_tribute_budget_base_units": (
                exact_tribute_budget_base_units
            ),
            "expected_release_authority_pda": release_pda,
            "expected_cal_receipt_pda": cal_receipt_pda,
        }
        # Freeze a detached plan value inside the evidence. Pointing evidence
        # back at the mutable outer plan creates a self-cycle as soon as the
        # snapshot is attached, which cannot cross the JSON repository bound.
        evidence_plan = dict(plan)
        release_evidence = {
            "domain": THRESHOLD_RELEASE_PLAN_DOMAIN,
            "plan": evidence_plan,
            "steps": steps,
            "hold_evidence_hash_hex": claim.get("hold_evidence_hash_hex"),
            "admission_plan_evidence_hash_hex": claim.get(
                "admission_plan_evidence_hash_hex"
            ),
        }
        plan["snapshot_evidence"] = release_evidence
        return plan, steps
