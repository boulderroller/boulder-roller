"""Privacy-safe read projection for the public on-chain Record Board.

The protocol Board remains immutable and economically authoritative.  This
module resolves each seated chain row back to one confirmed ride, applies that
ride's current public/privacy policy, and removes ineligible rows without
promoting or refilling the remaining seats.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Sequence

from ..utils.polyline import decode_gps_track
from .record_board_projection import project_competition_entries
from .ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    project_route_points,
)


_CHAIN_PLAN_STATES = {
    "attestation_confirmed",
    "completions_confirmed",
    "cal_confirmed",
    "projections_reconciled",
    "complete",
}
_RELEASE_EXECUTION_STATES = {
    "release_authority_confirmed",
    "completions_confirmed",
    "cal_confirmed",
    "projections_reconciled",
    "complete",
}
_THRESHOLD_RELEASE_PLAN_DOMAIN = "BR_THRESHOLD_HELD_RIDE_RELEASE_PLAN_V1"


class PublicRecordBoardPrivacyUnavailable(RuntimeError):
    """The public Board cannot be projected without risking private data."""


@dataclass(frozen=True)
class PublicRecordBoardProjection:
    """A filtered Board that retains the chain's original seat metadata."""

    entries: list[dict[str, Any]]
    kom_holder: Optional[str]
    kom_time_s: Optional[int]
    # Internal binding from the already-verified receipt/step, never a
    # wallet+time guess. Clients receive only the projected effort DTO.
    effort_ids: dict[str, str] = field(default_factory=dict)
    ride_ids: dict[str, str] = field(default_factory=dict)
    chain_entries: list[dict[str, Any]] = field(default_factory=list)


def _strict_int(value: Any, *, minimum: int = 0) -> Optional[int]:
    if isinstance(value, bool):
        return None
    if isinstance(value, float) and (
        not math.isfinite(value) or not value.is_integer()
    ):
        return None
    try:
        parsed = int(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if parsed < minimum:
        return None
    return parsed


def _timestamp(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        numeric = float(value)
        return numeric if math.isfinite(numeric) else None
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    try:
        numeric = float(raw)
    except ValueError:
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        numeric = parsed.timestamp()
    return numeric if math.isfinite(numeric) else None


def _completed_epoch(value: Any) -> Optional[int]:
    parsed = _timestamp(value)
    return int(parsed) if parsed is not None else None


def _point_is_visible(point: Mapping[str, Any]) -> bool:
    if point.get("redacted") is True:
        return False
    try:
        latitude = float(point.get("latitude"))
        longitude = float(point.get("longitude"))
    except (TypeError, ValueError):
        return False
    return (
        math.isfinite(latitude)
        and math.isfinite(longitude)
        and -90.0 <= latitude <= 90.0
        and -180.0 <= longitude <= 180.0
    )


def route_span_is_public(
    projected_points: Sequence[Mapping[str, Any]],
    *,
    start_offset_s: Any,
    end_offset_s: Any,
    ride_relative: bool = False,
) -> bool:
    """Return whether a complete climb window is visible in a projected route.

    The offsets are relative to the first route sample.  Every sampled interval
    overlapping the climb must have two visible endpoints; incomplete,
    unordered, or malformed time coverage fails closed.
    """
    # Exact D11 evidence already carries fractional seconds from recording
    # start. The legacy map projection retains its original offset convention.
    start = _timestamp(start_offset_s) if ride_relative else _strict_int(start_offset_s)
    end = _timestamp(end_offset_s) if ride_relative else _strict_int(end_offset_s)
    if start is None or end is None or start < 0 or end <= start or len(projected_points) < 2:
        return False

    absolute_times: list[float] = []
    for point in projected_points:
        if not isinstance(point, Mapping):
            return False
        parsed = _timestamp(point.get("timestamp"))
        if parsed is None:
            return False
        absolute_times.append(parsed)

    baseline = 0 if ride_relative else absolute_times[0]
    offsets = [value - baseline for value in absolute_times]
    if any(right < left for left, right in zip(offsets, offsets[1:])):
        return False
    if offsets[0] > start or offsets[-1] < end:
        return False

    covered = False
    for index in range(len(projected_points) - 1):
        left = offsets[index]
        right = offsets[index + 1]
        if right <= start or left >= end:
            continue
        covered = True
        if not _point_is_visible(projected_points[index]):
            return False
        if not _point_is_visible(projected_points[index + 1]):
            return False
    return covered


def _rows(response: Any) -> list[dict[str, Any]]:
    data = getattr(response, "data", None)
    if data is None:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )
    if not isinstance(data, list):
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )
    return [dict(row) for row in data if isinstance(row, Mapping)]


def _hash_text(value: Any) -> Optional[str]:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if isinstance(value, (bytes, bytearray)):
        return bytes(value).hex()
    if not isinstance(value, str):
        return None
    normalized = value.strip().lower()
    if normalized.startswith("\\x") or normalized.startswith("0x"):
        normalized = normalized[2:]
    return normalized or None


def _unique_by(rows: Sequence[Mapping[str, Any]], key: str) -> dict[str, dict[str, Any]]:
    unique: dict[str, dict[str, Any]] = {}
    duplicates: set[str] = set()
    for row in rows:
        value = row.get(key)
        if value in (None, ""):
            continue
        normalized = str(value)
        if normalized in unique:
            duplicates.add(normalized)
        else:
            unique[normalized] = dict(row)
    for duplicate in duplicates:
        unique.pop(duplicate, None)
    return unique


def _normalized_release_step(
    step: Mapping[str, Any],
    *,
    snapshots_by_id: Mapping[str, Mapping[str, Any]],
    executions_by_snapshot: Mapping[str, Mapping[str, Any]],
) -> Optional[dict[str, Any]]:
    """Bind one V3 release step to its immutable route-span evidence."""
    if _strict_int(step.get("completion_evidence_version")) != 3:
        return None
    snapshot_id = str(step.get("snapshot_id") or "")
    snapshot = snapshots_by_id.get(snapshot_id)
    execution = executions_by_snapshot.get(snapshot_id)
    if not snapshot or not execution:
        return None
    if execution.get("state") not in _RELEASE_EXECUTION_STATES:
        return None

    evidence = snapshot.get("snapshot_evidence")
    if not isinstance(evidence, Mapping):
        return None
    if evidence.get("domain") != _THRESHOLD_RELEASE_PLAN_DOMAIN:
        return None
    evidence_plan = evidence.get("plan")
    evidence_steps = evidence.get("steps")
    if not isinstance(evidence_plan, Mapping) or not isinstance(evidence_steps, list):
        return None

    ride_id = str(snapshot.get("ride_id") or "")
    user_id = str(snapshot.get("user_id") or "")
    release_authority_pda = str(
        execution.get("expected_release_authority_pda") or ""
    )
    release_wallet = str(execution.get("wallet") or "")
    if (
        not ride_id
        or not user_id
        or not release_authority_pda
        or not release_wallet
        or str(evidence_plan.get("ride_id") or "") != ride_id
        or str(evidence_plan.get("user_id") or "") != user_id
        or str(evidence_plan.get("wallet") or "") != release_wallet
        or str(evidence_plan.get("expected_release_authority_pda") or "")
        != release_authority_pda
    ):
        return None

    step_index = _strict_int(step.get("step_index"))
    if step_index is None:
        return None
    evidence_matches = [
        row
        for row in evidence_steps
        if isinstance(row, Mapping)
        and _strict_int(row.get("step_index")) == step_index
    ]
    if len(evidence_matches) != 1:
        return None
    frozen = evidence_matches[0]

    integer_fields = (
        "step_index",
        "vault_id",
        "completion_time_s",
        "exact_tribute_base_units",
        "completion_evidence_version",
    )
    for field in integer_fields:
        step_value = _strict_int(step.get(field))
        frozen_value = _strict_int(frozen.get(field))
        if step_value is None or frozen_value is None or step_value != frozen_value:
            return None
    text_fields = (
        "pattern_id",
        "vault_signature",
        "expected_receipt_pda",
    )
    if any(
        not str(step.get(field) or "")
        or str(step.get(field) or "") != str(frozen.get(field) or "")
        for field in text_fields
    ):
        return None
    step_completed_at = _timestamp(step.get("completed_at"))
    frozen_completed_at = _timestamp(frozen.get("completed_at"))
    if (
        step_completed_at is None
        or frozen_completed_at is None
        or step_completed_at != frozen_completed_at
    ):
        return None
    step_hash = _hash_text(step.get("completion_evidence_hash"))
    frozen_hash = _hash_text(frozen.get("completion_evidence_hash_hex"))
    if not step_hash or not frozen_hash or step_hash != frozen_hash:
        return None

    start_offset = _strict_int(frozen.get("segment_start_offset_s"))
    end_offset = _strict_int(frozen.get("segment_end_offset_s"))
    if start_offset is None or end_offset is None or end_offset <= start_offset:
        return None

    normalized = dict(step)
    normalized.update({
        "ride_id": ride_id,
        "release_user_id": user_id,
        "release_authority_pda": release_authority_pda,
        "release_wallet": release_wallet,
        "segment_start_offset_s": start_offset,
        "segment_end_offset_s": end_offset,
    })
    return normalized


def _query_projection_rows(
    client: Any,
    *,
    vault_id: int,
    completion_times: list[int],
) -> tuple[
    list[dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, dict[str, Any]],
    dict[str, list[dict[str, Any]]],
]:
    steps = _rows(
        client.from_("ride_economic_completion_steps")
        .select(
            "ride_id,pattern_id,vault_id,completion_time_s,completed_at,"
            "expected_receipt_pda,completion_evidence_hash,"
            "completion_evidence_version,state,actual_tx_signature,"
            "chain_confirmed_at,segment_start_offset_s,segment_end_offset_s"
        )
        .eq("vault_id", vault_id)
        .in_("state", ["confirmed", "projected"])
        .in_("completion_time_s", completion_times)
        .execute()
    )
    release_steps = _rows(
        client.from_("reward_threshold_release_steps")
        .select(
            "snapshot_id,step_index,pattern_id,vault_id,vault_signature,"
            "completion_time_s,completed_at,exact_tribute_base_units,"
            "completion_evidence_version,completion_evidence_hash,"
            "expected_receipt_pda,state,actual_tx_signature,chain_confirmed_at"
        )
        .eq("vault_id", vault_id)
        .in_("state", ["confirmed", "projected"])
        .in_("completion_time_s", completion_times)
        .execute()
    )
    release_snapshot_ids = sorted(
        {
            str(row["snapshot_id"])
            for row in release_steps
            if row.get("snapshot_id")
        }
    )
    if release_snapshot_ids:
        snapshots = _rows(
            client.from_("reward_threshold_release_snapshots")
            .select("id,ride_id,user_id,snapshot_evidence")
            .in_("id", release_snapshot_ids)
            .execute()
        )
        executions = _rows(
            client.from_("reward_threshold_release_executions")
            .select(
                "snapshot_id,wallet,expected_release_authority_pda,state"
            )
            .in_("snapshot_id", release_snapshot_ids)
            .execute()
        )
        snapshots_by_id = _unique_by(snapshots, "id")
        executions_by_snapshot = _unique_by(executions, "snapshot_id")
        steps.extend(
            normalized
            for step in release_steps
            if (
                normalized := _normalized_release_step(
                    step,
                    snapshots_by_id=snapshots_by_id,
                    executions_by_snapshot=executions_by_snapshot,
                )
            )
            is not None
        )
    ride_ids = sorted({str(row["ride_id"]) for row in steps if row.get("ride_id")})
    if not ride_ids:
        return steps, {}, {}, {}, {}, {}

    plans = _rows(
        client.from_("ride_economic_plans")
        .select("ride_id,user_id,wallet,expected_attestation_pda,state")
        .in_("ride_id", ride_ids)
        .execute()
    )
    receipt_pdas = sorted(
        {
            str(row["expected_receipt_pda"])
            for row in steps
            if row.get("expected_receipt_pda")
        }
    )
    receipts = (
        _rows(
            client.from_("indexed_climb_completion_receipts")
            .select(
                "pda,ride_attestation_pda,vault_pda,completion_evidence_hash,"
                "completion_evidence_version,release_authority_pda"
            )
            .in_("pda", receipt_pdas)
            .execute()
        )
        if receipt_pdas
        else []
    )
    rides = _rows(
        client.from_("rides")
        .select(
            "id,user_id,visibility,map_visibility,map_hide_start_m,"
            "map_hide_end_m,hide_from_leaderboards,moderation_state,"
            "ride_attestation_pda,gps_track"
        )
        .in_("id", ride_ids)
        .execute()
    )

    plans_by_ride = _unique_by(plans, "ride_id")
    receipts_by_pda = _unique_by(receipts, "pda")
    rides_by_id = _unique_by(rides, "id")

    user_ids = sorted(
        {
            str(plan["user_id"])
            for plan in plans_by_ride.values()
            if plan.get("user_id")
        }
    )
    users = (
        _rows(
            client.from_("users")
            .select("id,wallet,is_public,moderation_state")
            .in_("id", user_ids)
            .execute()
        )
        if user_ids
        else []
    )
    zones = (
        _rows(
            client.from_("privacy_zones")
            .select("user_id,latitude,longitude,radius_m")
            .in_("user_id", user_ids)
            .execute()
        )
        if user_ids
        else []
    )

    zones_by_user: dict[str, list[dict[str, Any]]] = {
        user_id: [] for user_id in user_ids
    }
    for zone in zones:
        user_id = str(zone.get("user_id") or "")
        if user_id in zones_by_user:
            zones_by_user[user_id].append(zone)

    return (
        steps,
        plans_by_ride,
        receipts_by_pda,
        rides_by_id,
        _unique_by(users, "id"),
        zones_by_user,
    )


def _entry_identity(entry: Mapping[str, Any]) -> Optional[tuple[str, int, int]]:
    wallet = str(entry.get("user") or "").strip()
    completion_time = _strict_int(entry.get("time_s"), minimum=1)
    recorded_at = _strict_int(entry.get("recorded_at"), minimum=1)
    if not wallet or completion_time is None or recorded_at is None:
        return None
    return wallet, completion_time, recorded_at


def _resolved_candidates(
    *,
    entry_identity: tuple[str, int, int],
    steps: Sequence[Mapping[str, Any]],
    plans_by_ride: Mapping[str, Mapping[str, Any]],
    receipts_by_pda: Mapping[str, Mapping[str, Any]],
    rides_by_id: Mapping[str, Mapping[str, Any]],
    vault_pda: str,
) -> list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]:
    wallet, completion_time, recorded_at = entry_identity
    resolved: list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]] = []
    for step in steps:
        if _strict_int(step.get("completion_time_s"), minimum=1) != completion_time:
            continue
        if _completed_epoch(step.get("completed_at")) != recorded_at:
            continue
        if step.get("state") not in {"confirmed", "projected"}:
            continue
        if not step.get("chain_confirmed_at"):
            continue
        if str(step.get("actual_tx_signature") or "").startswith("exists:"):
            continue
        evidence_version = _strict_int(step.get("completion_evidence_version"))
        if evidence_version not in {2, 3}:
            continue

        ride_id = str(step.get("ride_id") or "")
        receipt_pda = str(step.get("expected_receipt_pda") or "")
        plan = plans_by_ride.get(ride_id)
        receipt = receipts_by_pda.get(receipt_pda)
        ride = rides_by_id.get(ride_id)
        if not plan or not receipt or not ride:
            continue
        if plan.get("state") not in _CHAIN_PLAN_STATES:
            continue
        if str(plan.get("wallet") or "") != wallet:
            continue

        attestation_pda = str(plan.get("expected_attestation_pda") or "")
        if not attestation_pda:
            continue
        if str(ride.get("ride_attestation_pda") or "") != attestation_pda:
            continue
        if str(receipt.get("ride_attestation_pda") or "") != attestation_pda:
            continue
        if str(receipt.get("vault_pda") or "") != vault_pda:
            continue
        if _strict_int(receipt.get("completion_evidence_version")) != evidence_version:
            continue
        if evidence_version == 3 and (
            str(step.get("release_wallet") or "") != str(plan.get("wallet") or "")
            or str(step.get("release_user_id") or "")
            != str(plan.get("user_id") or "")
            or not str(step.get("release_authority_pda") or "")
            or str(receipt.get("release_authority_pda") or "")
            != str(step.get("release_authority_pda") or "")
        ):
            continue
        receipt_hash = _hash_text(receipt.get("completion_evidence_hash"))
        step_hash = _hash_text(step.get("completion_evidence_hash"))
        if not receipt_hash or not step_hash or receipt_hash != step_hash:
            continue
        if str(plan.get("user_id") or "") != str(ride.get("user_id") or ""):
            continue
        resolved.append((step, plan, ride))
    return resolved


def _ride_is_public(
    ride: Mapping[str, Any],
    profile: Optional[Mapping[str, Any]],
    *,
    expected_wallet: str,
) -> bool:
    if ride.get("visibility") != "public":
        return False
    if ride.get("hide_from_leaderboards") is not False:
        return False
    if str(ride.get("moderation_state") or "").lower() != "visible":
        return False
    if not profile or profile.get("is_public") is not True:
        return False
    if str(profile.get("moderation_state") or "").lower() != "visible":
        return False
    return str(profile.get("wallet") or "") == expected_wallet


def project_public_record_board(
    client: Any,
    *,
    vault_row: Mapping[str, Any],
    raw_entries: Sequence[Mapping[str, Any]],
) -> PublicRecordBoardProjection:
    """Build the public Board projection without changing chain rank or state."""
    ranked_entries = project_competition_entries(raw_entries)
    valid_identities = [
        identity
        for identity in (_entry_identity(entry) for entry in ranked_entries)
        if identity is not None
    ]
    if not valid_identities:
        return PublicRecordBoardProjection(entries=[], kom_holder=None, kom_time_s=None)

    vault_id = _strict_int(vault_row.get("id"))
    vault_pda = str(vault_row.get("pda") or "").strip()
    if vault_id is None or not vault_pda:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        )

    try:
        (
            steps,
            plans_by_ride,
            receipts_by_pda,
            rides_by_id,
            users_by_id,
            zones_by_user,
        ) = _query_projection_rows(
            client,
            vault_id=vault_id,
            completion_times=sorted({identity[1] for identity in valid_identities}),
        )
    except PublicRecordBoardPrivacyUnavailable:
        raise
    except Exception as exc:
        raise PublicRecordBoardPrivacyUnavailable(
            "public Record Board privacy projection unavailable"
        ) from exc

    public_entries: list[dict[str, Any]] = []
    effort_ids: dict[str, str] = {}
    ride_ids: dict[str, str] = {}
    for entry in ranked_entries:
        identity = _entry_identity(entry)
        if identity is None:
            continue
        candidates = _resolved_candidates(
            entry_identity=identity,
            steps=steps,
            plans_by_ride=plans_by_ride,
            receipts_by_pda=receipts_by_pda,
            rides_by_id=rides_by_id,
            vault_pda=vault_pda,
        )
        if len(candidates) != 1:
            continue

        step, plan, ride = candidates[0]
        user_id = str(plan.get("user_id") or "")
        if not _ride_is_public(
            ride,
            users_by_id.get(user_id),
            expected_wallet=identity[0],
        ):
            continue

        try:
            policy = RidePrivacyPolicy.from_values(
                visibility=ride.get("visibility"),
                map_visibility=ride.get("map_visibility"),
                map_hide_start_m=ride.get("map_hide_start_m"),
                map_hide_end_m=ride.get("map_hide_end_m"),
            )
            points = decode_gps_track(ride.get("gps_track"))
            if not points:
                continue
            projected_points = project_route_points(
                points,
                policy,
                privacy_zones=zones_by_user.get(user_id),
            )
        except (
            PrivacySettingsUnavailable,
            IndexError,
            KeyError,
            OverflowError,
            TypeError,
            ValueError,
        ):
            continue

        if not route_span_is_public(
            projected_points,
            start_offset_s=step.get("segment_start_offset_s"),
            end_offset_s=step.get("segment_end_offset_s"),
        ):
            continue
        public_entries.append(dict(entry))
        if step.get("pattern_id"):
            effort_ids[identity[0]] = str(step["pattern_id"])
            ride_ids[identity[0]] = str(ride["id"])

    raw_kom_holder = str(vault_row.get("kom_holder") or "").strip()
    raw_kom_time = _strict_int(vault_row.get("kom_time_s"), minimum=1)
    kom_is_public = any(
        str(entry.get("user") or "") == raw_kom_holder
        and _strict_int(entry.get("time_s"), minimum=1) == raw_kom_time
        and _strict_int(entry.get("rank"), minimum=1) == 1
        for entry in public_entries
    )
    return PublicRecordBoardProjection(
        entries=public_entries,
        kom_holder=raw_kom_holder if kom_is_public else None,
        kom_time_s=raw_kom_time if kom_is_public and raw_kom_time is not None else None,
        effort_ids=effort_ids,
        ride_ids=ride_ids,
        chain_entries=ranked_entries,
    )
