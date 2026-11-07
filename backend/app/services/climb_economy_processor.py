"""Climb/vault economy orchestration for processed ride patterns."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple
from uuid import UUID

from ..repositories import UserRepository, VaultRepository
from . import ride_economic_plan_builder
from .climb_vault import ClimbVaultService
from .projection_writer import ProjectionWriter
from .ride_executor import RideExecutor
from .sample_time import infer_sample_time_base, sample_in_time_window

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from .ride_economic_coordinator import CompletionStepDraft


class VaultCompletionChainError(RuntimeError):
    """Raised when a live vault completion cannot be committed on-chain."""


def _mark_match_abstention(climb: Any, reason: str) -> None:
    reasons = list(getattr(climb, "abstention_reasons", None) or [])
    if reason not in reasons:
        reasons.append(reason)
    climb.abstention_reasons = reasons
    climb.economic_eligible = False


def is_vault_live_for_completion(indexed_vault: Optional[Dict[str, Any]]) -> bool:
    """Live completion writes require the exact finalized V4-B canon binding."""
    if not indexed_vault:
        return False
    try:
        canon_version = int(indexed_vault.get("canon_version") or 0)
        seed_generation = int(
            indexed_vault.get("vault_activation_seed_generation")
        )
        zero_counters = tuple(
            int(indexed_vault.get(field))
            for field in (
                "vault_activation_seed_completions_written",
                "vault_activation_matched_users",
                "vault_activation_matched_completions",
            )
        )
        timestamps = tuple(
            int(indexed_vault.get(field))
            for field in (
                "vault_activation_created_at",
                "vault_activation_activated_at",
                "vault_activation_last_seed_at",
                "vault_activation_seed_cutoff_at",
            )
        )
    except (TypeError, ValueError):
        return False
    if any(isinstance(indexed_vault.get(field), bool) for field in (
        "canon_version",
        "vault_activation_seed_generation",
        "vault_activation_seed_completions_written",
        "vault_activation_matched_users",
        "vault_activation_matched_completions",
        "vault_activation_created_at",
        "vault_activation_activated_at",
        "vault_activation_last_seed_at",
        "vault_activation_seed_cutoff_at",
    )):
        return False
    evidence_hash = str(
        indexed_vault.get("vault_activation_evidence_hash") or ""
    ).lower()
    expected_activation_pda = str(
        indexed_vault.get("expected_vault_activation_pda") or ""
    )
    return (
        indexed_vault.get("canon_binding_status") == "active"
        and indexed_vault.get("canon_activation_status") == "finalized"
        and bool(indexed_vault.get("canon_climb_id"))
        and bool(indexed_vault.get("canon_id"))
        and 1 <= canon_version <= 0xFFFF
        and bool(re.fullmatch(
            r"[0-9a-f]{64}",
            str(indexed_vault.get("canonical_profile_hash_hex") or ""),
        ))
        and bool(expected_activation_pda)
        and str(indexed_vault.get("vault_activation_pda") or "")
        == expected_activation_pda
        and indexed_vault.get("constructor_evidence_verified") is True
        and str(indexed_vault.get("constructor_evidence_hash") or "").lower()
        == evidence_hash
        and indexed_vault.get("vault_activation_is_active") is True
        and seed_generation == 2
        and zero_counters == (0, 0, 0)
        and indexed_vault.get("vault_activation_leaderboard_seeded") is True
        and bool(re.fullmatch(r"[0-9a-f]{64}", evidence_hash))
        and evidence_hash != "0" * 64
        and timestamps[0] > 0
        and timestamps[0] == timestamps[1] == timestamps[2] == timestamps[3]
    )


class ClimbEconomyProcessor:
    """Match detected climbs to vaults and execute completion economics.

    This service is still orchestration, not a new truth role: on-chain writes
    go through RideExecutor and read-model mirrors go through ProjectionWriter.
    """

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        vault_repo: VaultRepository,
        vault_service: ClimbVaultService,
        ride_executor: RideExecutor,
        projection_writer: ProjectionWriter,
    ) -> None:
        self.user_repo = user_repo
        self.vault_repo = vault_repo
        self.vault_service = vault_service
        self.ride_executor = ride_executor
        self.projection_writer = projection_writer

    async def match_climbs_to_vault(
        self,
        *,
        climb_patterns: List,
        tile_samples: List[Dict[str, Any]],
        user_id: UUID,
        ride_id: UUID,
        completed_at: datetime,
        cal_earned: int = 0,
        total_ride_duration_s: int = 0,
        ride_hash: Optional[bytes] = None,
        strict: bool = False,
        user_wallet: Optional[str] = None,
    ) -> Tuple[int, List[Dict[str, Any]]]:
        """Match detected climbs to vaults and record chain-backed completions."""
        if user_wallet is None:
            user_wallet = await self.user_repo.get_user_wallet(user_id)
        total_cal_distributed = 0
        vault_allocations: List[Dict[str, Any]] = []

        for climb in climb_patterns:
            trace = getattr(climb, "match_trace", None)
            if not isinstance(trace, dict):
                _mark_match_abstention(climb, "MATCH:canon_traversal_required")
                continue
            try:
                registry_id = UUID(str(trace["registry_id"]))
                canon_id = UUID(str(trace["canon_id"]))
                canon_version = int(trace["canon_version"])
                profile_hash = str(
                    trace.get("profile_hash")
                    or (trace.get("canonical_profile_hash") or {}).get("value")
                    or ""
                ).lower()
                if (
                    registry_id.int == 0
                    or canon_id.int == 0
                    or not 1 <= canon_version <= 0xFFFF
                    or not re.fullmatch(r"[0-9a-f]{64}", profile_hash)
                    or profile_hash == "0" * 64
                ):
                    raise ValueError("invalid exact canon identity")
            except (KeyError, TypeError, ValueError):
                _mark_match_abstention(climb, "MATCH:invalid_canon_traversal")
                continue

            indexed_vault = await self.vault_repo.find_canon_vault_binding(
                registry_id=registry_id,
                canon_id=canon_id,
                canon_version=canon_version,
                profile_hash_hex=profile_hash,
            )
            if not is_vault_live_for_completion(indexed_vault):
                _mark_match_abstention(climb, "MATCH:canon_activation_required")
                continue

            reasons = [
                reason
                for reason in list(getattr(climb, "abstention_reasons", None) or [])
                if reason != "MATCH:canon_activation_required"
            ]
            climb.abstention_reasons = reasons
            # Exact activation clears only its own pending reason. Sensor,
            # effort, or any other abstention remains authoritative.
            climb.economic_eligible = not reasons
            vault_id = indexed_vault.get("id")
            if vault_id is None:
                vault_id = indexed_vault.get("vault_id")
            climb.indexed_vault_id = vault_id
            climb.indexed_vault_name = indexed_vault.get("name")
            climb.canon_vault_binding = indexed_vault
            if ride_hash is None:
                self._project_vault_enrichment(
                    climb=climb,
                    indexed_vault=indexed_vault,
                    vault_id=vault_id,
                    tile_samples=tile_samples,
                )
                continue
            raise VaultCompletionChainError(
                "direct climb completion economics are disabled; "
                "freeze and execute a ride economic plan"
            )

        return total_cal_distributed, vault_allocations

    async def build_completion_plan(
        self,
        *,
        climb_patterns: List,
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
    ) -> Tuple[List["CompletionStepDraft"], List[Dict[str, Any]]]:
        """Build immutable completion steps without economic side effects."""
        return await ride_economic_plan_builder.build_completion_plan(
            self,
            climb_patterns=climb_patterns,
            tile_samples=tile_samples,
            raw_climb_samples=raw_climb_samples,
            user_id=user_id,
            user_wallet=user_wallet,
            ride_id=ride_id,
            ride_hash=ride_hash,
            completed_at=completed_at,
            exact_ride_cal_base_units=exact_ride_cal_base_units,
            total_ride_duration_s=total_ride_duration_s,
            reward_ftp_w=reward_ftp_w,
            effort_trim=effort_trim,
            ride_started_at=ride_started_at,
        )

    def _project_vault_enrichment(
        self,
        *,
        climb: Any,
        indexed_vault: Dict[str, Any],
        vault_id: Any,
        tile_samples: List[Dict[str, Any]],
    ) -> None:
        if not indexed_vault.get("start_lat") and getattr(climb, "start_lat", None):
            self.projection_writer.backfill_vault_gps(
                vault_id=vault_id,
                start_lat=climb.start_lat,
                start_lon=climb.start_lon,
                end_lat=getattr(climb, "end_lat", None),
                end_lon=getattr(climb, "end_lon", None),
            )

        if (
            not indexed_vault.get("polyline_json")
            and getattr(climb, "start_offset_s", None) is not None
            and getattr(climb, "end_offset_s", None) is not None
        ):
            try:
                sample_time_base = infer_sample_time_base(tile_samples)
                climb_samples = [
                    s
                    for s in tile_samples
                    if sample_in_time_window(
                        s,
                        climb.start_offset_s,
                        climb.end_offset_s,
                        base_time=sample_time_base,
                    )
                    and s.get("lat") is not None
                    and s.get("lon") is not None
                ]
                if len(climb_samples) >= 5:
                    polyline_data = [
                        [round(s["lat"], 6), round(s["lon"], 6)]
                        for s in climb_samples
                    ]
                    self.projection_writer.backfill_vault_polyline(
                        vault_id=vault_id,
                        polyline_data=polyline_data,
                    )
            except Exception as exc:
                logger.debug(f"[VaultPolyline] Sample assembly failed: {exc}")
