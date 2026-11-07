"""Immutable ride-economic plan types and canonical freeze payload."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Mapping, Sequence
from uuid import UUID

from ..repositories.ride_economic import RideEconomicRepository
from .cal_tribute_policy import (
    CAL_TRIBUTE_POWER_METRICS_VERSION,
    CAL_TRIBUTE_POLICY_VERSION,
    MIN_SEGMENT_POWER_COVERAGE_BPS,
    MIN_SEGMENT_POWER_SAMPLE_COUNT,
    calculate_intensity_bps,
    calculate_ride_tribute_budget,
    calculate_segment_tss_base_units,
)
from .protocol_ints import (
    U16_MAX,
    U32_MAX,
    U64_MAX,
    U128_MAX,
    U8_MAX,
    exact_positive_uint,
    exact_uint,
)
from .ride_attester import OnchainRideIdentity
from .ride_executor import RideExecutor
from .ride_effort_trim import subtract, intersect, completion_window_ms
from .reward_threshold import THRESHOLD_PROVISIONAL_HOLD_POLICY
from .reward_ftp import (
    DEFAULT_REWARD_FTP_W,
    NETWORK_DEFAULT_REWARD_FTP_SOURCE,
    REWARD_FTP_POLICY_VERSION,
    RewardFtpSnapshot,
)


def _utc_iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat()


@dataclass(frozen=True)
class CompletionStepDraft:
    pattern_id: UUID
    vault_id: int
    vault_signature: str
    completion_time_s: int
    completed_at: datetime
    exact_tribute_base_units: int
    intensity_bps: int
    completion_evidence_hash: bytes
    completion_evidence_version: int
    segment_start_offset_s: int = 0
    segment_end_offset_s: int = 0
    segment_np_w: int | None = None
    segment_np_milliwatts: int | None = None
    segment_np_duration_s: int = 0
    segment_power_sample_count: int = 0
    segment_power_coverage_bps: int = 0
    segment_power_metrics_version: str = "workout_parse_metrics_v1"
    tribute_weight: int = 0
    climb_distance_m: int | None = None
    climb_vert_m: int | None = None


@dataclass(frozen=True)
class RideEconomicPlanDraft:
    ride_id: UUID
    user_id: UUID
    wallet: str
    identity: OnchainRideIdentity
    policy_version: str
    reward_policy: str
    tribute_policy_version: str
    started_at: datetime
    completed_at: datetime
    total_tss: int
    total_distance_m: int
    total_vert_m: int
    exact_cal_base_units: int
    climbs_crossed: int
    completion_steps: Sequence[CompletionStepDraft]
    effort_trim: Any
    reward_ftp_w: int = DEFAULT_REWARD_FTP_W
    reward_ftp_source: str = NETWORK_DEFAULT_REWARD_FTP_SOURCE
    reward_ftp_authority_id: str | None = None
    reward_ftp_policy_version: str = REWARD_FTP_POLICY_VERSION
    threshold_hold_evidence: Mapping[str, Any] | None = None


async def freeze_ride_economic_plan(
    *,
    repository: RideEconomicRepository,
    executor: RideExecutor,
    draft: RideEconomicPlanDraft,
) -> Dict[str, Any]:
    ride_hash = bytes(draft.identity.ride_hash)
    commitment = bytes(draft.identity.attestation_commitment)
    if len(ride_hash) != 32 or len(commitment) != 32:
        raise ValueError("ride hash and attestation commitment must be 32 bytes")
    if not draft.wallet:
        raise ValueError("wallet is required for a ride economic plan")
    reward_ftp_snapshot = RewardFtpSnapshot.from_row(
        {
            "reward_ftp_w": draft.reward_ftp_w,
            "reward_ftp_source": draft.reward_ftp_source,
            "reward_ftp_authority_id": draft.reward_ftp_authority_id,
            "reward_ftp_policy_version": draft.reward_ftp_policy_version,
        }
    )
    if draft.tribute_policy_version != CAL_TRIBUTE_POLICY_VERSION:
        raise ValueError(
            "new economic plans require the ratified CAL tribute policy"
        )

    attestation_pda = executor.derive_attestation_pda(
        rider_wallet=draft.wallet, ride_hash=ride_hash
    )
    cal_receipt_pda = executor.derive_cal_receipt_pda(
        rider_wallet=draft.wallet, ride_hash=ride_hash
    )
    seen_vaults: set[int] = set()
    seen_patterns: set[UUID] = set()
    steps: list[Dict[str, Any]] = []
    ordered = sorted(
        draft.completion_steps,
        key=lambda step: (int(step.vault_id), str(step.pattern_id)),
    )
    for step_index, step in enumerate(ordered):
        vault_id = exact_uint(step.vault_id, field="vault_id", maximum=U64_MAX)
        if vault_id in seen_vaults:
            raise ValueError(f"duplicate ride completion vault {vault_id}")
        if step.pattern_id in seen_patterns:
            raise ValueError(f"duplicate ride completion pattern {step.pattern_id}")
        seen_vaults.add(vault_id)
        seen_patterns.add(step.pattern_id)
        evidence_hash = bytes(step.completion_evidence_hash)
        if len(evidence_hash) != 32:
            raise ValueError("completion evidence hash must be 32 bytes")
        evidence_version = exact_uint(
            step.completion_evidence_version,
            field="completion_evidence_version",
            maximum=U8_MAX,
        )
        if evidence_version != 2:
            raise ValueError("new economic plans require completion evidence version 2")
        expected_evidence_hash = executor.build_completion_evidence_v2(
            rider_wallet=draft.wallet,
            ride_hash=ride_hash,
            vault_id=vault_id,
            completion_time_s=step.completion_time_s,
            cal_tribute=step.exact_tribute_base_units,
        )
        if evidence_hash != expected_evidence_hash:
            raise ValueError("V2 completion evidence hash does not bind frozen tribute")
        completion_time_s = exact_positive_uint(
            step.completion_time_s,
            field="completion_time_s",
            maximum=U32_MAX,
        )
        segment_start_offset_s = exact_uint(
            step.segment_start_offset_s,
            field="segment_start_offset_s",
            maximum=U32_MAX,
        )
        segment_end_offset_s = exact_uint(
            step.segment_end_offset_s,
            field="segment_end_offset_s",
            maximum=U32_MAX,
        )
        if segment_end_offset_s < segment_start_offset_s:
            raise ValueError("segment end offset cannot precede its start")
        segment_power_sample_count = exact_uint(
            step.segment_power_sample_count,
            field="segment_power_sample_count",
            maximum=U32_MAX,
        )
        segment_power_coverage_bps = exact_uint(
            step.segment_power_coverage_bps,
            field="segment_power_coverage_bps",
            maximum=10_000,
        )
        if step.segment_power_metrics_version != CAL_TRIBUTE_POWER_METRICS_VERSION:
            raise ValueError("unsupported climb-window power metrics version")
        segment_np_w = (
            exact_uint(step.segment_np_w, field="segment_np_w", maximum=U16_MAX)
            if step.segment_np_w is not None
            else None
        )
        segment_np_milliwatts = (
            exact_uint(
                step.segment_np_milliwatts,
                field="segment_np_milliwatts",
                maximum=U16_MAX * 1_000,
            )
            if step.segment_np_milliwatts is not None
            else None
        )
        segment_np_duration_s = exact_uint(
            step.segment_np_duration_s,
            field="segment_np_duration_s",
            maximum=U32_MAX,
        )
        # Inclusive whole-second window: completion_time + 1 samples, ±1 for rounding.
        window_samples = segment_end_offset_s - segment_start_offset_s + 1
        if segment_np_duration_s > window_samples:
            raise ValueError("NP duration exceeds climb window")
        if window_samples > completion_time_s + 2:
            raise ValueError("segment window does not match completion time")
        if (
            segment_power_sample_count < MIN_SEGMENT_POWER_SAMPLE_COUNT
            or segment_power_coverage_bps < MIN_SEGMENT_POWER_COVERAGE_BPS
        ) and (segment_np_w is not None or segment_np_milliwatts is not None):
            raise ValueError("insufficient segment power cannot authorize tribute")
        if (segment_np_w is None) != (segment_np_milliwatts is None):
            raise ValueError("rounded and exact segment NP evidence must agree")
        if segment_np_milliwatts is not None and segment_np_duration_s == 0:
            raise ValueError("frozen segment NP requires a positive NP duration")
        if (
            segment_np_milliwatts is not None
            and segment_np_w != (segment_np_milliwatts + 500) // 1_000
        ):
            raise ValueError("rounded segment NP does not match frozen milliwatts")
        tribute_weight = exact_uint(
            step.tribute_weight,
            field="tribute_weight",
            maximum=U64_MAX,
        )
        if tribute_weight != 0:
            raise ValueError("new measured-TSS plans do not use allocation weights")
        intensity_bps = exact_uint(
            step.intensity_bps,
            field="intensity_bps",
            maximum=U32_MAX,
        )
        if intensity_bps != calculate_intensity_bps(
            segment_np_milliwatts=segment_np_milliwatts,
            reward_ftp_w=reward_ftp_snapshot.ftp_w,
        ):
            raise ValueError("frozen intensity does not use immutable reward FTP")
        exact_tribute_base_units = exact_uint(
            step.exact_tribute_base_units,
            field="exact_tribute_base_units",
            maximum=U64_MAX,
        )
        expected_tribute = calculate_segment_tss_base_units(
            segment_np_duration_s=segment_np_duration_s,
            segment_np_milliwatts=segment_np_milliwatts,
            reward_ftp_w=reward_ftp_snapshot.ftp_w,
        )
        if exact_tribute_base_units != expected_tribute:
            raise ValueError("frozen tribute does not match measured climb TSS")
        steps.append(
            {
                "step_index": step_index,
                "pattern_id": str(step.pattern_id),
                "vault_id": vault_id,
                "vault_signature": step.vault_signature,
                "completion_time_s": completion_time_s,
                "completed_at": _utc_iso(step.completed_at),
                "exact_tribute_base_units": exact_tribute_base_units,
                "intensity_bps": intensity_bps,
                "segment_start_offset_s": segment_start_offset_s,
                "segment_end_offset_s": segment_end_offset_s,
                "segment_np_w": segment_np_w,
                "segment_np_milliwatts": segment_np_milliwatts,
                "segment_np_duration_s": segment_np_duration_s,
                "segment_power_sample_count": segment_power_sample_count,
                "segment_power_coverage_bps": segment_power_coverage_bps,
                "segment_power_metrics_version": step.segment_power_metrics_version,
                "tribute_weight": tribute_weight,
                "climb_distance_m": (
                    exact_uint(
                        step.climb_distance_m,
                        field="climb_distance_m",
                        maximum=U32_MAX,
                    )
                    if step.climb_distance_m is not None
                    else None
                ),
                "climb_vert_m": (
                    exact_uint(
                        step.climb_vert_m,
                        field="climb_vert_m",
                        maximum=U32_MAX,
                    )
                    if step.climb_vert_m is not None
                    else None
                ),
                "completion_evidence_hash_hex": evidence_hash.hex(),
                "completion_evidence_version": evidence_version,
                "expected_receipt_pda": executor.derive_completion_receipt_pda(
                    rider_wallet=draft.wallet,
                    ride_hash=ride_hash,
                    vault_id=vault_id,
                ),
            }
        )

    exact_cal_base_units = exact_uint(
        draft.exact_cal_base_units,
        field="exact_cal_base_units",
        maximum=U64_MAX,
    )
    by_window = sorted(
        steps,
        key=lambda step: (
            step["segment_start_offset_s"],
            step["segment_end_offset_s"],
        ),
    )
    for previous, current in zip(by_window, by_window[1:]):
        if current["segment_start_offset_s"] <= previous["segment_end_offset_s"]:
            raise ValueError("overlapping eligible climb windows require review")
    expected_allocations = [step["exact_tribute_base_units"] for step in steps]
    exact_tribute_budget_base_units = calculate_ride_tribute_budget(
        exact_cal_base_units,
        expected_allocations,
    )
    tribute_total = exact_uint(
        sum(expected_allocations),
        field="exact_tribute_base_units",
        maximum=U128_MAX,
    )
    trim = draft.effort_trim
    if subtract(trim.paid_ms, trim.effort_ms):
        raise ValueError("paid effort outside parsed effort")
    if draft.reward_policy != THRESHOLD_PROVISIONAL_HOLD_POLICY and (
        exact_cal_base_units == 0
    ) != (not trim.paid_ms):
        raise ValueError("CAL and paid effort must both be empty or both positive")
    for step in steps:
        if not intersect([completion_window_ms(draft.started_at, step["segment_start_offset_s"], step["segment_end_offset_s"])], trim.paid_ms):
            raise ValueError("completion outside paid effort")
    plan = {
        "effort_trim": trim.payload(),
        "ride_id": str(draft.ride_id),
        "user_id": str(draft.user_id),
        "wallet": draft.wallet,
        "ride_hash_hex": ride_hash.hex(),
        "attestation_commitment_hex": commitment.hex(),
        "parser_version": exact_uint(
            draft.identity.parser_version,
            field="parser_version",
            maximum=U32_MAX,
        ),
        "policy_version": draft.policy_version,
        "reward_policy": draft.reward_policy,
        "tribute_policy_version": draft.tribute_policy_version,
        "reward_ftp_w": exact_positive_uint(
            reward_ftp_snapshot.ftp_w, field="reward_ftp_w", maximum=U16_MAX
        ),
        "reward_ftp_source": reward_ftp_snapshot.source,
        "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
        "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
        "source_kind": exact_uint(
            draft.identity.source_kind, field="source_kind", maximum=U8_MAX
        ),
        "started_at": _utc_iso(draft.started_at),
        "completed_at": _utc_iso(draft.completed_at),
        "total_tss": exact_uint(
            draft.total_tss, field="total_tss", maximum=U32_MAX
        ),
        "total_distance_m": exact_uint(
            draft.total_distance_m, field="total_distance_m", maximum=U32_MAX
        ),
        "total_vert_m": exact_uint(
            draft.total_vert_m, field="total_vert_m", maximum=U32_MAX
        ),
        "exact_cal_base_units": exact_cal_base_units,
        "exact_tribute_budget_base_units": exact_tribute_budget_base_units,
        "climbs_crossed": exact_uint(
            draft.climbs_crossed, field="climbs_crossed", maximum=U16_MAX
        ),
        "exact_tribute_base_units": tribute_total,
        "expected_attestation_pda": attestation_pda,
        "expected_cal_receipt_pda": cal_receipt_pda,
    }
    evidence_steps = [
        {key: value for key, value in step.items() if key != "pattern_id"}
        for step in steps
    ]
    evidence = {"domain": "BR_RIDE_ECONOMIC_PLAN_V5", "plan": plan, "steps": evidence_steps}
    plan["plan_evidence_hash_hex"] = hashlib.sha256(
        json.dumps(evidence, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if draft.threshold_hold_evidence is None:
        return await repository.freeze_plan(plan=plan, steps=steps)
    threshold_hold = {
        "ride_id": str(draft.ride_id),
        "user_id": str(draft.user_id),
        "ride_started_at": _utc_iso(draft.started_at),
        "admission_plan_evidence_hash_hex": plan["plan_evidence_hash_hex"],
        "hold_evidence": dict(draft.threshold_hold_evidence),
    }
    return await repository.freeze_plan(
        plan=plan,
        steps=steps,
        threshold_hold=threshold_hold,
    )
