"""Build immutable per-climb steps for a ride economic plan."""

from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Tuple
from uuid import UUID

from .cal_tribute_policy import (
    MIN_SEGMENT_POWER_COVERAGE_BPS,
    MIN_SEGMENT_POWER_SAMPLE_COUNT,
    calculate_intensity_bps,
    calculate_ride_tribute_budget,
    calculate_segment_tss_base_units,
)
from .ride_economic_coordinator import CompletionStepDraft
from .workout_parse_adapter import calculate_segment_power_metrics_rust
from .ride_effort_trim import completion_window_ms, intersect, subtract, epoch_ms, ClimbTributeExceedsPaidCalError

if TYPE_CHECKING:
    from .climb_economy_processor import ClimbEconomyProcessor


logger = logging.getLogger(__name__)


async def build_completion_plan(
    processor: "ClimbEconomyProcessor",
    *,
    climb_patterns: List[Any],
    tile_samples: List[Dict[str, Any]],
    raw_climb_samples: List[Dict[str, Any]],
    user_id: UUID,
    user_wallet: str,
    ride_id: UUID,
    ride_hash: bytes,
    completed_at: datetime,
    exact_ride_cal_base_units: int,
    total_ride_duration_s: int,
    reward_ftp_w: int,
    effort_trim=None,
    ride_started_at=None,
) -> Tuple[List[CompletionStepDraft], List[Dict[str, Any]]]:
    """Match and validate climbs without writing DB or chain state."""
    from .climb_economy_processor import (
        is_vault_live_for_completion,
    )

    if len(ride_hash) != 32:
        raise ValueError("ride_hash must be exactly 32 bytes")
    if total_ride_duration_s <= 0:
        raise ValueError("total_ride_duration_s must be positive")

    await processor.match_climbs_to_vault(
        climb_patterns=climb_patterns,
        tile_samples=tile_samples,
        user_id=user_id,
        ride_id=ride_id,
        completed_at=completed_at,
        cal_earned=0,
        total_ride_duration_s=total_ride_duration_s,
        ride_hash=None,
        strict=True,
        user_wallet=user_wallet,
    )

    planned_by_vault: Dict[int, Tuple[CompletionStepDraft, Dict[str, Any]]] = {}
    for climb in climb_patterns:
        vault_id = getattr(climb, "indexed_vault_id", None)
        pattern_id = getattr(climb, "id", None)
        if vault_id is not None and pattern_id is None:
            raise ValueError("matched climb is missing its pattern identity")
        if (
            vault_id is None
            or pattern_id is None
            or not getattr(climb, "economic_eligible", True)
            or not getattr(climb, "time_s", None)
        ):
            continue
        indexed_vault = getattr(climb, "canon_vault_binding", None)
        try:
            raw_binding_vault_id = indexed_vault.get("id")
            if raw_binding_vault_id is None:
                raw_binding_vault_id = indexed_vault.get("vault_id")
            binding_vault_id = int(raw_binding_vault_id)
        except (AttributeError, TypeError, ValueError):
            binding_vault_id = -1
        if (
            binding_vault_id != int(vault_id)
            or not is_vault_live_for_completion(indexed_vault)
        ):
            reasons = list(getattr(climb, "abstention_reasons", None) or [])
            if "MATCH:canon_activation_required" not in reasons:
                reasons.append("MATCH:canon_activation_required")
            climb.abstention_reasons = reasons
            climb.economic_eligible = False
            continue
        vault_signature = str(indexed_vault["signature_hex"])
        validation = await processor.vault_repo.validate_climb_time(
            vault_signature=vault_signature,
            time_seconds=int(climb.time_s),
            climb_distance_m=getattr(climb, "distance_m", None),
            climb_vert_m=getattr(climb, "vert_m", None),
        )
        if not validation["is_valid"]:
            logger.warning(
                "[RideEconomics] Excluding invalid climb time from plan: "
                "ride=%s vault=%s reason=%s",
                ride_id,
                vault_id,
                validation.get("error_message"),
            )
            continue

        start_offset_s = getattr(climb, "start_time_offset_s", None)
        end_offset_s = getattr(climb, "end_time_offset_s", None)
        if start_offset_s is None or end_offset_s is None:
            raise ValueError("matched climb is missing frozen time offsets")
        window = completion_window_ms(ride_started_at, start_offset_s, end_offset_s) if effort_trim is not None else None
        if effort_trim is not None:
            if not intersect([window], effort_trim.paid_ms):
                continue
            if any(int(w["vault_id"]) == int(vault_id) and intersect([window], [(w["start_ms"],w["end_ms"])]) for w in effort_trim.covered_completion_windows):
                continue
        keep_ms_relative = None
        if (
            effort_trim is not None
            and effort_trim.paid_ms != effort_trim.effort_ms
            and subtract([window], effort_trim.paid_ms)
        ):
            origin = epoch_ms(ride_started_at)
            keep_ms_relative = [
                (a - origin, b - origin) for a, b in effort_trim.paid_ms
            ]
        segment_metrics = calculate_segment_power_metrics_rust(
            raw_climb_samples,
            start_offset_s=start_offset_s,
            end_offset_s=end_offset_s,
            keep_ms_relative=keep_ms_relative,
        )
        # The frozen offsets are whole-second roundings of the two gate crossings,
        # so the inclusive 1 Hz sample window holds completion_time + 1 samples
        # (one more or fewer from rounding). NP may cover that whole window and
        # never more; the window itself must agree with the completion time.
        window_samples = end_offset_s - start_offset_s + 1
        if segment_metrics.normalized_power_duration_s > window_samples:
            raise ValueError("NP duration exceeds climb window")
        if window_samples > int(climb.time_s) + 2:
            raise ValueError("segment window does not match completion time")
        segment_np_w = segment_metrics.normalized_power_w
        segment_np_milliwatts = segment_metrics.normalized_power_milliwatts
        if (
            segment_metrics.power_sample_count < MIN_SEGMENT_POWER_SAMPLE_COUNT
            or segment_metrics.power_sample_coverage_bps
            < MIN_SEGMENT_POWER_COVERAGE_BPS
        ):
            segment_np_w = None
            segment_np_milliwatts = None
        segment_tss_base_units = calculate_segment_tss_base_units(
            segment_np_duration_s=segment_metrics.normalized_power_duration_s,
            segment_np_milliwatts=segment_np_milliwatts,
            reward_ftp_w=reward_ftp_w,
        )
        intensity_bps = calculate_intensity_bps(
            segment_np_milliwatts=segment_np_milliwatts,
            reward_ftp_w=reward_ftp_w,
        )
        draft = CompletionStepDraft(
            pattern_id=UUID(str(pattern_id)),
            vault_id=int(vault_id),
            vault_signature=vault_signature,
            completion_time_s=int(climb.time_s),
            completed_at=completed_at,
            exact_tribute_base_units=segment_tss_base_units,
            intensity_bps=intensity_bps,
            completion_evidence_hash=b"\x00" * 32,
            completion_evidence_version=2,
            segment_start_offset_s=start_offset_s,
            segment_end_offset_s=end_offset_s,
            segment_np_w=segment_np_w,
            segment_np_milliwatts=segment_np_milliwatts,
            segment_np_duration_s=segment_metrics.normalized_power_duration_s,
            segment_power_sample_count=segment_metrics.power_sample_count,
            segment_power_coverage_bps=segment_metrics.power_sample_coverage_bps,
            segment_power_metrics_version=segment_metrics.metrics_version,
            tribute_weight=0,
            climb_distance_m=(
                int(getattr(climb, "distance_m"))
                if getattr(climb, "distance_m", None) is not None
                else None
            ),
            climb_vert_m=(
                int(getattr(climb, "vert_m"))
                if getattr(climb, "vert_m", None) is not None
                else None
            ),
        )
        allocation = {
            "vault_id": int(vault_id),
            "vault_signature": vault_signature,
            "cal_tribute": 0,
            "time_in_vault_s": int(climb.time_s),
            "intensity_bps": intensity_bps,
            "segment_np_w": segment_np_w,
            "segment_np_milliwatts": segment_np_milliwatts,
            "segment_np_duration_s": segment_metrics.normalized_power_duration_s,
            "segment_power_sample_count": segment_metrics.power_sample_count,
            "segment_power_coverage_bps": segment_metrics.power_sample_coverage_bps,
            "segment_power_metrics_version": segment_metrics.metrics_version,
            "tribute_weight": 0,
        }
        existing = planned_by_vault.get(int(vault_id))
        if existing is None or draft.completion_time_s < existing[0].completion_time_s:
            planned_by_vault[int(vault_id)] = (draft, allocation)

    ordered = [planned_by_vault[key] for key in sorted(planned_by_vault)]
    by_window = sorted(
        (draft for draft, _ in ordered),
        key=lambda draft: (draft.segment_start_offset_s, draft.segment_end_offset_s),
    )
    for previous, current in zip(by_window, by_window[1:]):
        if current.segment_start_offset_s <= previous.segment_end_offset_s:
            raise ValueError("overlapping eligible climb windows require review")
    try:
        calculate_ride_tribute_budget(exact_ride_cal_base_units, (draft.exact_tribute_base_units for draft, _ in ordered))
    except ValueError as exc:
        if effort_trim is not None and effort_trim.paid_ms != effort_trim.effort_ms:
            raise ClimbTributeExceedsPaidCalError(str(exc)) from exc
        raise
    steps = [
        replace(
            draft,
            completion_evidence_hash=processor.ride_executor.build_completion_evidence_v2(
                rider_wallet=user_wallet,
                ride_hash=ride_hash,
                vault_id=draft.vault_id,
                completion_time_s=draft.completion_time_s,
                cal_tribute=draft.exact_tribute_base_units,
            ),
        )
        for draft, _ in ordered
    ]
    allocations = [
        {**allocation, "cal_tribute": draft.exact_tribute_base_units}
        for draft, allocation in ordered
    ]
    return steps, allocations
