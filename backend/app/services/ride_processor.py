"""
Ride Processor: Orchestrates the ride processing pipeline.

Multi-Phase Processing (Strava-style progressive loading):
    Phase 1 (<5s):  Parse → Metrics → Streams → GPS → status=metrics_ready
    Phase 2 (30-60s): Tiles → Patterns → Vaults → Leaderboards → status=enriched
    Phase 3 (background): CAL → Achievements → On-chain → status=completed

Legacy Flow (monolithic, for backward compatibility):
    Upload → Parse → Metrics → Tile Projection → Pattern Detection → Rewards
"""
from __future__ import annotations

import inspect
import logging
from .ride_weather import capture_ride_weather
import time
from dataclasses import dataclass, replace
from copy import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, List, Optional, Union
from uuid import UUID

from ..repositories import (
    # Domain repositories
    AchievementRepository,
    CanonRepository,
    FitnessRepository,
    NotificationRepository,
    PatternRepository,
    RideRepository,
    RideEconomicRepository,
    TileRepository,
    TokenRepository,
    UserRepository,
    VaultRepository,
    # Factories
    create_achievement_repository,
    create_fitness_repository,
    create_notification_repository,
    create_pattern_repository,
    create_ride_repository,
    create_tile_repository,
    create_token_repository,
    create_user_repository,
    create_vault_repository,
    # Client for services that need direct access
    get_supabase_client,
)
from ..solana_client import BoulderRollersClient, get_solana_client
from .achievement_detector import AchievementDetector
from .cal_tribute_policy import CAL_TRIBUTE_POLICY_VERSION
from .canon_traversal import CanonTraversalService
from .canon_traversal_evidence import detector_compatible_samples
from .climb_economy_processor import ClimbEconomyProcessor
from .default_ride_title import default_ride_title, place_label_for_ride
from .elevation_correction import (
    correct_route_elevation,
    load_dem_grid,
    route_points_from_gps_dicts,
)
from .fitness_analytics import FitnessAnalyticsService
from .pattern_engine import PatternEngine, PatternResults
from .projection_writer import ProjectionWriter
from .ride_enrichment_service import CanonMatchingBlocked, RideEnrichmentService
from .ride_executor import RideExecutor
from .ride_economic_coordinator import (
    RideEconomicCoordinator,
    RideEconomicOutcome,
    RideEconomicPlanDraft,
)
from .ride_economic_terminal_projector import RideEconomicTerminalProjector
from ..repositories.ride_economic import StaleEffortCoverageError
from .ride_effort_policy import (
    build_paid_effort_policy,
    AUTHORITATIVE_METRICS_VERSION,
    CAL_DECIMALS_MULTIPLIER,
    FUTURE_ACTIVITY_REVIEW_REASON,
    HEART_RATE_THRESHOLD_REVIEW_REASON,
    INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON,
    INVALID_ACTIVITY_DURATION_REVIEW_REASON,
    MISSING_ACTIVITY_TIMESTAMP_REVIEW_REASON,
    NON_AUTHORITATIVE_METRICS_REVIEW_REASON,
    PRE_ECONOMY_REVIEW_REASON,
    RIDE_EFFORT_POLICY_VERSION,
    ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON,
    STALE_ACTIVITY_REVIEW_REASON,
    RideEffortPolicy,
    _calculate_cal_amounts,
    _calculate_economic_cal_amounts,
    build_ride_effort_policy,
)
from .ride_projection_store import RideProjectionStore
from .ride_attester import (
    OnchainRideIdentity,
    PreliminaryAttestationCheck,
    RideAttester,
    _source_kind_from_file_type,
    evaluate_preliminary_attestation,
)
from .ride_idle_evidence import assess_idle_recording
from .ride_metrics import RideMetrics
from .reward_ftp import (
    DEFAULT_REWARD_FTP_W,
    RewardFtpSnapshot,
)
from .reward_threshold import (
    project_threshold_hold_policy,
    requires_threshold_hold,
    register_threshold_effort,
    threshold_candidate_review_reason,
    threshold_effort_evidence_or_empty,
)
from .threshold_release_planner import (
    THRESHOLD_PROVISIONAL_HOLD_POLICY,
    build_threshold_hold_evidence,
)
from .tile_service import TileService, TileAttributionService
from .climb_vault import ClimbVaultService
from .notification_service import create_notification_service
from .file_storage import create_file_storage_service
from .ride_effort_trim import (
    EffortTrim,
    resolve_effort_trim,
    PaidEffortEvidenceUnavailableError,
    PaidEffortEvidenceMismatchError,
    ClimbTributeExceedsPaidCalError,
    completion_window_ms,
    encode,
    intersect,
)
from .workout_parse_adapter import effort_spans_ms_rust

# Backward-compatible re-exports for the attestation DTOs. The canonical
# home of these symbols is `services/ride_attester.py` per BACKEND_TRUTHS
# §5.1; new code should import from `ride_attester` directly.
#
# Type pin (BACKEND_TRUTHS §6.1 / PROTOCOL_TRUTHS §2.3): the
# `OnchainRideIdentity` dataclass field `parser_version: int` remains
# a plain Python int on the backend side, matching the mobile-side
# `CURRENT_PARSER_VERSION` integer literal and the on-chain u32. Any
# widen here (str / Optional / float) would silently mis-compare on
# the attestation hash. The dataclass itself is defined in
# `ride_attester.py`; this comment keeps the alignment-gate scanner
# anchored to `ride_processor.py` as the integration point.
__all__ = [
    "OnchainRideIdentity",
    "PreliminaryAttestationCheck",
    "AUTHORITATIVE_METRICS_VERSION",
    "CAL_DECIMALS_MULTIPLIER",
    "FUTURE_ACTIVITY_REVIEW_REASON",
    "HEART_RATE_THRESHOLD_REVIEW_REASON",
    "INSUFFICIENT_POWER_COVERAGE_REVIEW_REASON",
    "INVALID_ACTIVITY_DURATION_REVIEW_REASON",
    "MISSING_ACTIVITY_TIMESTAMP_REVIEW_REASON",
    "NON_AUTHORITATIVE_METRICS_REVIEW_REASON",
    "PRE_ECONOMY_REVIEW_REASON",
    "ROUTE_ESTIMATE_ECONOMIC_REVIEW_REASON",
    "STALE_ACTIVITY_REVIEW_REASON",
    "RideEffortPolicy",
    "evaluate_preliminary_attestation",
    "_calculate_cal_amounts",
    "_calculate_economic_cal_amounts",
    "build_ride_effort_policy",
    "RideProcessor",
]


logger = logging.getLogger(__name__)


RIDER_LEVEL_TSS_STEP = 200.0
MISSING_WALLET_ECONOMIC_REVIEW_REASON = "missing_wallet_for_economics"
MISSING_ECONOMIC_TSS_REVIEW_REASON = "missing_economic_tss_snapshot"


def _unfrozen_ride_economic_fields(
    ride_row: Optional[Dict[str, Any]],
    *,
    threshold_source_fields: Dict[str, Any],
    economic_tss: Optional[float],
    reward_ftp_snapshot: Optional[RewardFtpSnapshot],
    effort_spans_ms=None,
) -> Dict[str, Any]:
    """Return only economic facts that have not already crossed their freeze."""
    existing = ride_row or {}
    fields: Dict[str, Any] = {}
    if existing.get("effort_spans_ms") is None and effort_spans_ms is not None:
        fields["effort_spans_ms"] = encode(effort_spans_ms)
    if existing.get("threshold_source_evidence") is None:
        fields.update(threshold_source_fields)
    if existing.get("economic_tss") is None and economic_tss is not None:
        fields["economic_tss"] = economic_tss
    if existing.get("reward_ftp_w") is None and reward_ftp_snapshot is not None:
        fields.update(
            {
                "reward_ftp_w": reward_ftp_snapshot.ftp_w,
                "reward_ftp_source": reward_ftp_snapshot.source,
                "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
                "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
            }
        )
    return fields


def _frozen_ride_effort_policy(
    ride_row: Optional[Dict[str, Any]],
) -> Optional[RideEffortPolicy]:
    """Rehydrate the policy coupled to an existing economic TSS snapshot."""
    existing = ride_row or {}
    economic_tss = existing.get("economic_tss")
    required = (
        "effort_evidence_tier",
        "reward_policy",
        "estimated_cal",
        "rewardable_cal",
        "tributable_cal",
    )
    if economic_tss is None:
        return None
    if any(existing.get(key) is None for key in required):
        # A crash can persist the immutable TSS before the coupled policy
        # columns. Resume only from the already-stored ride facts; a parser
        # upgrade must not supply a different denominator or evidence tier.
        return build_ride_effort_policy(
            _economic_metrics_source(existing),
            blocking_review_reason=(
                str(existing["review_reason"])
                if existing.get("review_reason") is not None
                else None
            ),
            completed_at=existing.get("completed_at"),
            started_at=existing.get("started_at"),
        )
    try:
        _, exact_cal = _calculate_cal_amounts(Decimal(str(economic_tss)))
        estimated_cal = int(existing["estimated_cal"])
        rewardable_cal = int(existing["rewardable_cal"])
        tributable_cal = int(existing["tributable_cal"])
    except (TypeError, ValueError, OverflowError, InvalidOperation):
        return None
    return RideEffortPolicy(
        effort_evidence_tier=str(existing["effort_evidence_tier"]),
        reward_policy=str(existing["reward_policy"]),
        estimated_cal=estimated_cal,
        rewardable_cal=rewardable_cal,
        tributable_cal=tributable_cal,
        estimated_cal_base_units=exact_cal if estimated_cal > 0 else 0,
        rewardable_cal_base_units=exact_cal if rewardable_cal > 0 else 0,
        tributable_cal_base_units=exact_cal if tributable_cal > 0 else 0,
        review_reason=(
            str(existing["review_reason"])
            if existing.get("review_reason") is not None
            else None
        ),
    )


def _snapshot_file_policy(snapshot_policy, economic_tss, fallback):
    """Keep the admitted decision, deriving amounts from frozen whole-file TSS."""
    if snapshot_policy is None:
        return fallback

    display, exact = _calculate_cal_amounts(float(economic_tss))
    if snapshot_policy.reward_policy == "not_counted":
        display, exact = 0, 0
    rewardable = snapshot_policy.reward_policy in (
        "rewardable",
        THRESHOLD_PROVISIONAL_HOLD_POLICY,
    )
    return replace(
        snapshot_policy,
        reward_policy="rewardable" if rewardable else snapshot_policy.reward_policy,
        estimated_cal=display,
        estimated_cal_base_units=exact,
        rewardable_cal=display if rewardable else 0,
        rewardable_cal_base_units=exact if rewardable else 0,
        tributable_cal=display if rewardable else 0,
        tributable_cal_base_units=exact if rewardable else 0,
    )


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _coerce_phase2_timestamp(
    value: Any,
    *,
    base_time: Optional[datetime] = None,
) -> Optional[datetime]:
    """Normalize GPS/store timestamps to datetimes before sensor stream lookup."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            return None
    if isinstance(value, (int, float)):
        try:
            numeric = float(value)
            # Compressed map tracks store elapsed seconds, while legacy JSON
            # tracks may contain Unix seconds. Phase 2 previously interpreted
            # every elapsed value as January 1970.
            if base_time is not None and abs(numeric) < 1_000_000_000:
                return base_time + timedelta(seconds=numeric)
            return datetime.fromtimestamp(numeric, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    return None


def _rider_level_for_total_tss(total_tss: float) -> int:
    """Fortnite-style rider level: durable projected progress from total TSS."""
    return int(max(0.0, total_tss) // RIDER_LEVEL_TSS_STEP) + 1


def _economic_metrics_source(ride_data: Dict[str, Any]) -> Dict[str, Any]:
    """Use the immutable economic TSS while retaining shared sensor evidence."""
    metrics = dict(ride_data)
    if ride_data.get("economic_tss") is not None:
        metrics["tss"] = ride_data["economic_tss"]
    return metrics


async def _build_progression_snapshot(
    *,
    user_repo: UserRepository,
    user_id: UUID,
    ride_tss: float,
    current_ride_prior_tss: float = 0.0,
) -> Dict[str, Optional[Union[float, int]]]:
    """Build a retry-stable rider progression snapshot for status clients.

    User stats are a backend projection, not chain truth. If that projection is
    unavailable, the route can still expose the ride's TSS delta from the ride
    row, but we avoid fabricating cumulative totals or levels.
    """
    stats_fn = getattr(user_repo, "get_user_stats", None)
    if not callable(stats_fn):
        return {
            "total_tss_after": None,
            "level_delta": None,
            "level_after": None,
        }

    try:
        maybe_stats = stats_fn(str(user_id))
        stats = await maybe_stats if inspect.isawaitable(maybe_stats) else maybe_stats
    except Exception:
        logger.warning(
            "[RideProcessor] Could not load prior TSS for progression snapshot",
            exc_info=True,
        )
        return {
            "total_tss_after": None,
            "level_delta": None,
            "level_after": None,
        }

    if not isinstance(stats, dict):
        return {
            "total_tss_after": None,
            "level_delta": None,
            "level_after": None,
        }

    projected_total_before = max(
        0.0,
        _safe_float(stats.get("total_economic_tss", stats.get("total_tss")))
        - max(0.0, current_ride_prior_tss),
    )
    total_tss_after = projected_total_before + max(0.0, ride_tss)
    level_before = _rider_level_for_total_tss(projected_total_before)
    level_after = _rider_level_for_total_tss(total_tss_after)

    return {
        "total_tss_after": total_tss_after,
        "level_delta": max(0, level_after - level_before),
        "level_after": level_after,
    }


@dataclass
class ProcessingResult:
    metrics: RideMetrics
    patterns_detected: int
    achievements_earned: int
    dung_minted: int
    tx_signature: Optional[str]


class RideProcessor:
    """Orchestrates ride file processing pipeline."""

    def __init__(
        self,
        # Domain repositories
        ride_repo: Optional[RideRepository] = None,
        tile_repo: Optional[TileRepository] = None,
        user_repo: Optional[UserRepository] = None,
        token_repo: Optional[TokenRepository] = None,
        pattern_repo: Optional[PatternRepository] = None,
        achievement_repo: Optional[AchievementRepository] = None,
        vault_repo: Optional[VaultRepository] = None,
        fitness_repo: Optional[FitnessRepository] = None,
        notification_repo: Optional[NotificationRepository] = None,
        # Other services
        solana: Optional[BoulderRollersClient] = None,
        achievement_detector: Optional[AchievementDetector] = None,
        tile_service: Optional[TileService] = None,
        pattern_engine: Optional[PatternEngine] = None,
        tile_attribution_service: Optional[TileAttributionService] = None,
        vault_service: Optional[ClimbVaultService] = None,
        ride_attester: Optional[RideAttester] = None,
        ride_projection_store: Optional[RideProjectionStore] = None,
        climb_economy_processor: Optional[ClimbEconomyProcessor] = None,
        canon_traversal_service: Optional[CanonTraversalService] = None,
        ride_enrichment_service: Optional[RideEnrichmentService] = None,
        projection_writer: Optional[ProjectionWriter] = None,
        ride_executor: Optional[RideExecutor] = None,
        ride_economic_repository: Optional[RideEconomicRepository] = None,
        ride_economic_coordinator: Optional[RideEconomicCoordinator] = None,
        ride_economic_terminal_projector: Optional[
            RideEconomicTerminalProjector
        ] = None,
    ) -> None:
        # Domain repositories
        self.ride_repo = ride_repo or create_ride_repository()
        self.tile_repo = tile_repo or create_tile_repository()
        self.user_repo = user_repo or create_user_repository()
        self.token_repo = token_repo or create_token_repository()
        self.pattern_repo = pattern_repo or create_pattern_repository()
        self.achievement_repo = achievement_repo or create_achievement_repository()
        self.vault_repo = vault_repo or create_vault_repository()
        self.fitness_repo = fitness_repo or create_fitness_repository()
        self.notification_repo = notification_repo or create_notification_repository()

        # Get shared client for services that need direct access
        self._client = get_supabase_client()

        # Other services
        self.solana = solana or get_solana_client()
        self.achievement_detector = achievement_detector or AchievementDetector()
        self.analytics_service = FitnessAnalyticsService(self.fitness_repo, self.ride_repo)
        self.tile_service = tile_service or TileService()
        self.pattern_engine = pattern_engine or PatternEngine()

        # Initialize attribution service
        self.tile_attribution_service = tile_attribution_service or TileAttributionService(self._client)

        # Initialize vault service for matching climbs to canonical vault
        self.vault_service = vault_service or ClimbVaultService(self._client)

        # Attester role (BACKEND_TRUTHS §5.1): parse/canonicalize/hash and
        # preliminary-hash gate. Never submits transactions or writes
        # projection tables.
        self.ride_attester = ride_attester or RideAttester()

        # Ride read-model persistence (streams, GPS, phase status, pattern
        # rows). This is downstream of attestation and separate from both
        # on-chain execution and chain-indexer projection writes.
        self.ride_projection_store = ride_projection_store or RideProjectionStore(
            ride_repo=self.ride_repo,
            tile_repo=self.tile_repo,
            pattern_repo=self.pattern_repo,
            user_repo=self.user_repo,
            client=self._client,
            tile_service=self.tile_service,
        )

        # Projector role (BACKEND_TRUTHS §5.3 / §10): read-layer writes to
        # indexer tables (indexed_vaults, vault_completions mirror) and
        # indexer-side RPC counters. Never authoritative.
        self.projection_writer = projection_writer or ProjectionWriter(self._client)
        # Executor role (BACKEND_TRUTHS §5.2): on-chain transaction
        # submission against already-attested ride state. Never authoritative
        # over parser/canonicalization or projection tables.
        self.ride_executor = ride_executor or RideExecutor()
        self.ride_economic_repository = (
            ride_economic_repository or RideEconomicRepository(self._client)
        )
        self.ride_economic_terminal_projector = (
            ride_economic_terminal_projector
            or RideEconomicTerminalProjector(
                economic_repository=self.ride_economic_repository,
                ride_repository=self.ride_repo,
                notification_repository=self.notification_repo,
            )
        )
        self.ride_economic_coordinator = (
            ride_economic_coordinator
            or RideEconomicCoordinator(
                repository=self.ride_economic_repository,
                executor=self.ride_executor,
            )
        )

        self.climb_economy_processor = (
            climb_economy_processor
            or ClimbEconomyProcessor(
                user_repo=self.user_repo,
                vault_repo=self.vault_repo,
                vault_service=self.vault_service,
                ride_executor=self.ride_executor,
                projection_writer=self.projection_writer,
            )
        )
        self.canon_traversal_service = (
            canon_traversal_service
            or CanonTraversalService(CanonRepository(self._client))
        )
        self.ride_enrichment_service = (
            ride_enrichment_service
            or RideEnrichmentService(
                user_repo=self.user_repo,
                tile_repo=self.tile_repo,
                pattern_engine=self.pattern_engine,
                tile_attribution_service=self.tile_attribution_service,
                climb_economy_processor=self.climb_economy_processor,
                ride_projection_store=self.ride_projection_store,
                canon_traversal_service=self.canon_traversal_service,
            )
        )

    async def _bind_reward_ftp_snapshot(
        self,
        *,
        ride_id: UUID,
        activity_started_at: Optional[datetime],
    ) -> RewardFtpSnapshot:
        row = await self.ride_repo.bind_reward_ftp_snapshot(
            ride_id=ride_id,
            activity_started_at=activity_started_at,
        )
        if not isinstance(row, dict):
            raise ValueError("reward FTP authority did not return a ride snapshot")
        return RewardFtpSnapshot.from_row(row)

    async def _freeze_ride_economic_plan(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        user_wallet: str,
        identity: OnchainRideIdentity,
        effort_policy: RideEffortPolicy,
        economic_metrics: Any,
        file_idle_reason=None,
        effort_spans_ms,
        load_native_activity,
        started_at: datetime,
        completed_at: datetime,
        total_tss: int,
        total_distance_m: int,
        total_vert_m: int,
        total_ride_duration_s: int,
        reward_ftp_snapshot: RewardFtpSnapshot,
        pattern_results: Optional[PatternResults],
        tile_samples: List[Dict[str, Any]],
        raw_climb_samples: List[Dict[str, Any]],
    ) -> tuple[
        Optional[Dict[str, Any]],
        List[Dict[str, Any]],
        RideEffortPolicy,
        Optional[EffortTrim],
    ]:
        trim = None
        loaded_idle_reason = file_idle_reason
        loaded_native = None
        completion_spans_ms = [
            completion_window_ms(
                started_at, climb.start_time_offset_s, climb.end_time_offset_s
            )
            for climb in getattr(pattern_results, "climb_patterns", [])
            if getattr(climb, "start_time_offset_s", None) is not None
            and getattr(climb, "end_time_offset_s", None) is not None
        ]

        async def checked_native_loader():
            nonlocal loaded_idle_reason, loaded_native
            if loaded_native is None:
                loaded_native = await load_native_activity()
                if file_idle_reason is None:
                    loaded_idle_reason = assess_idle_recording(
                        loaded_native.records
                    ).review_reason
            return loaded_native

        for attempt in range(3):
            if pattern_results is not None:
                pattern_results.vault_allocations = []
            try:
                if effort_spans_ms is None:
                    native = await checked_native_loader()
                    effort_spans_ms = effort_spans_ms_rust(native)
                    await self.ride_repo.update_ride_metadata(
                        str(ride_id), {"effort_spans_ms": encode(effort_spans_ms)}
                    )
                trim = await resolve_effort_trim(
                    repository=self.ride_economic_repository,
                    ride_id=ride_id,
                    user_id=user_id,
                    effort_ms=effort_spans_ms,
                    completion_spans_ms=completion_spans_ms,
                    load_native_activity=checked_native_loader,
                    reward_ftp_w=reward_ftp_snapshot.ftp_w,
                )
                if loaded_idle_reason and not trim.frozen:
                    policy = build_ride_effort_policy(
                        economic_metrics, blocking_review_reason=loaded_idle_reason
                    )
                    return None, [], policy, trim
                paid_policy = build_paid_effort_policy(
                    effort_policy,
                    trim,
                    started_at=started_at,
                    completed_at=completed_at,
                )
                if trim.paid_metrics is not None and not trim.frozen:
                    native = await checked_native_loader()
                    idle = assess_idle_recording(native.records, keep_ms=trim.paid_ms)
                    if idle.review_reason:
                        paid_policy = build_ride_effort_policy(
                            economic_metrics,
                            blocking_review_reason=idle.review_reason,
                        )
                if paid_policy.requires_economic_review:
                    return None, [], paid_policy, trim
                hold_required = (
                    requires_threshold_hold(reward_ftp_snapshot)
                    and paid_policy.is_rewardable
                )
                completion_steps = []
                allocations: List[Dict[str, Any]] = []
                if (
                    paid_policy.is_rewardable
                    and pattern_results
                    and pattern_results.climb_patterns
                ):
                    completion_steps, allocations = (
                        await self.climb_economy_processor.build_completion_plan(
                            climb_patterns=pattern_results.climb_patterns,
                            tile_samples=tile_samples,
                            raw_climb_samples=raw_climb_samples,
                            user_id=user_id,
                            user_wallet=user_wallet,
                            ride_id=ride_id,
                            ride_hash=bytes(identity.ride_hash),
                            completed_at=completed_at,
                            # Retain the admission effort budget while measuring hold
                            # evidence. The zero parent below authorizes no payment;
                            # release reprices these inputs at the established Threshold.
                            exact_ride_cal_base_units=paid_policy.rewardable_cal_base_units,
                            total_ride_duration_s=total_ride_duration_s,
                            reward_ftp_w=reward_ftp_snapshot.ftp_w,
                            effort_trim=trim,
                            ride_started_at=started_at,
                        )
                    )
                    pattern_results.vault_allocations = allocations

                provisional_completion_steps = completion_steps
                threshold_hold_evidence = None
                if hold_required:
                    # A provisional hold is evidence-gated before the immutable zero
                    # parent is even submitted. The repository then freezes both in
                    # one database transaction.
                    threshold_hold_evidence = build_threshold_hold_evidence(
                        metrics=trim.paid_metrics or economic_metrics,
                        effort_trim=trim,
                        completion_steps=provisional_completion_steps,
                        started_at=started_at,
                        completed_at=completed_at,
                    )
                    completion_steps = []
                    allocations = []
                    if pattern_results is not None:
                        pattern_results.vault_allocations = []

                frozen = await self.ride_economic_coordinator.freeze_plan(
                    RideEconomicPlanDraft(
                        ride_id=ride_id,
                        user_id=user_id,
                        wallet=user_wallet,
                        identity=identity,
                        policy_version=RIDE_EFFORT_POLICY_VERSION,
                        reward_policy=(
                            THRESHOLD_PROVISIONAL_HOLD_POLICY
                            if hold_required
                            else paid_policy.reward_policy
                        ),
                        tribute_policy_version=CAL_TRIBUTE_POLICY_VERSION,
                        started_at=started_at,
                        completed_at=completed_at,
                        total_tss=(
                            0
                            if hold_required
                            or (
                                not trim.paid_ms
                                and intersect(trim.effort_ms, trim.covered_ms)
                            )
                            else int(
                                trim.paid_metrics.tss
                                if trim.paid_metrics is not None
                                else total_tss
                            )
                        ),
                        effort_trim=trim,
                        total_distance_m=int(total_distance_m),
                        total_vert_m=int(total_vert_m),
                        exact_cal_base_units=(
                            0
                            if hold_required
                            else paid_policy.rewardable_cal_base_units
                        ),
                        climbs_crossed=(
                            len(pattern_results.climb_patterns)
                            if pattern_results
                            else 0
                        ),
                        completion_steps=completion_steps,
                        reward_ftp_w=reward_ftp_snapshot.ftp_w,
                        reward_ftp_source=reward_ftp_snapshot.source,
                        reward_ftp_authority_id=reward_ftp_snapshot.authority_id,
                        reward_ftp_policy_version=reward_ftp_snapshot.policy_version,
                        threshold_hold_evidence=threshold_hold_evidence,
                    )
                )
                return frozen, allocations, paid_policy, trim
            except StaleEffortCoverageError:
                if attempt == 2:
                    raise
            except (
                PaidEffortEvidenceUnavailableError,
                PaidEffortEvidenceMismatchError,
                ClimbTributeExceedsPaidCalError,
            ) as exc:
                reason = (
                    "paid_effort_evidence_unavailable"
                    if isinstance(exc, PaidEffortEvidenceUnavailableError)
                    else (
                        "paid_effort_evidence_mismatch"
                        if isinstance(exc, PaidEffortEvidenceMismatchError)
                        else "climb_tribute_exceeds_paid_cal"
                    )
                )
                if pattern_results:
                    pattern_results.vault_allocations = []
                policy = build_ride_effort_policy(
                    economic_metrics, blocking_review_reason=reason
                )
                return None, [], policy, trim

    async def _publish_nats_event(self, subject: str, payload: Dict[str, Any]) -> None:
        """
        Best-effort publish a NATS JetStream event.

        Never blocks ride processing — failures are logged and swallowed.
        """
        try:
            from .nats_client import get_nats_client
            client = get_nats_client()
            await client.publish(subject, payload)
        except Exception as exc:
            logger.warning(f"[NATS] Best-effort publish failed for {subject}: {exc}")

    async def _emit_notification(self, **payload: Any) -> None:
        """Best-effort notification.v1 producer hook for ride lifecycles."""
        create_event = getattr(self.notification_repo, "create_event_notification", None)
        if not callable(create_event):
            return
        try:
            result = create_event(**payload)
            if inspect.isawaitable(result):
                await result
        except Exception:
            logger.warning(
                "[RideProcessor] Failed to emit %s notification for ride %s",
                payload.get("notification_type"),
                (payload.get("metadata") or {}).get("ride_id") or payload.get("target_id"),
                exc_info=True,
            )

    async def _emit_ride_finalized_notification(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        wallet: Optional[str],
        cal_earned: int,
        dung_minted: int,
        tx_signature: Optional[str],
    ) -> None:
        await self._emit_notification(
            user_id=str(user_id),
            wallet=wallet,
            notification_type="ride_finalized",
            title="Ride finalized",
            message="Your ride is finalized and ready to review.",
            target_type="ride",
            target_id=str(ride_id),
            metadata={
                "ride_id": str(ride_id),
                "cal_earned": cal_earned,
                "dung_minted": dung_minted,
                "tx_signature": tx_signature,
            },
            dedupe_key=f"ride_finalized:{ride_id}",
        )

    async def _emit_ride_failed_notification(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        phase: str,
        message: str,
    ) -> None:
        wallet = None
        try:
            wallet = await self.user_repo.get_user_wallet(user_id)
        except Exception:
            logger.warning("[RideProcessor] Could not resolve wallet for failed ride notification", exc_info=True)
        await self._emit_notification(
            user_id=str(user_id),
            wallet=wallet,
            notification_type="ride_failed",
            title="Ride needs attention",
            message=message,
            target_type="ride",
            target_id=str(ride_id),
            metadata={
                "ride_id": str(ride_id),
                "phase": phase,
                "error_message": message,
            },
            dedupe_key=f"ride_failed:{ride_id}:{phase}",
        )

    async def _emit_record_board_notifications(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        wallet: Optional[str],
        vault_allocations: List[Dict[str, Any]],
    ) -> None:
        for allocation in vault_allocations:
            vault_signature = allocation.get("vault_signature")
            if not vault_signature:
                continue
            await self._emit_notification(
                user_id=str(user_id),
                wallet=wallet,
                notification_type="record_rank_moved",
                title="Record Board updated",
                message="Your climb completion was recorded.",
                target_type="record_board",
                target_id=str(allocation.get("vault_id") or vault_signature),
                metadata={
                    "ride_id": str(ride_id),
                    "vault_id": allocation.get("vault_id"),
                    "vault_signature": vault_signature,
                    "cal_tribute": allocation.get("cal_tribute"),
                    "time_in_vault_s": allocation.get("time_in_vault_s"),
                },
                dedupe_key=f"record_rank_moved:{ride_id}:{vault_signature}",
            )

    async def process_ride(
        self,
        ride_id: UUID,
        file_data_b64: str,
        file_type: str,
        user_id: UUID,
        user_weight_kg: float = 75.0,
        user_ftp_w: int = 200,
        file_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Main processing orchestration.

        Args:
            file_bytes: Optional raw file bytes. If provided, skips base64 decode
                        and passes directly to Rust parser (faster).
        """
        try:
            logger.info(f"[RideProcessor] Starting processing for ride {ride_id}")
            await self.ride_repo.update_ride_status(ride_id, "processing")
            ride_row = await self.ride_repo.get_ride(str(ride_id))
            attested_ride = self.ride_attester.prepare_ride(
                file_data_b64=file_data_b64,
                file_type=file_type,
                file_bytes=file_bytes,
                ride_row=ride_row,
                user_weight_kg=user_weight_kg,
                user_ftp_w=user_ftp_w,
                reward_ftp_w=DEFAULT_REWARD_FTP_W,
            )
            onchain_ride_identity = attested_ride.onchain_identity
            preliminary_attestation = attested_ride.preliminary_check
            parsed_ride = attested_ride.parsed_ride
            threshold_evidence = threshold_effort_evidence_or_empty(parsed_ride)
            metrics = attested_ride.metrics
            reward_ftp_snapshot = await self._bind_reward_ftp_snapshot(
                ride_id=ride_id,
                activity_started_at=parsed_ride.started_at,
            )
            economic_metrics = attested_ride.economic_metrics or metrics
            if reward_ftp_snapshot.ftp_w != attested_ride.reward_ftp_w:
                economic_metrics = self.ride_attester.calculate_metrics(
                    parsed_ride=parsed_ride,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=reward_ftp_snapshot.ftp_w,
                )
            economic_tss = float(
                (ride_row or {}).get("economic_tss")
                if (ride_row or {}).get("economic_tss") is not None
                else economic_metrics.tss or 0
            )
            idle_evidence = (
                assess_idle_recording(parsed_ride.records)
                if (ride_row or {}).get("economic_tss") is None
                else None
            )
            frozen_economic_fields = _unfrozen_ride_economic_fields(
                ride_row,
                threshold_source_fields=threshold_evidence.source.as_ride_fields(),
                effort_spans_ms=effort_spans_ms_rust(parsed_ride),
                economic_tss=economic_tss,
                reward_ftp_snapshot=reward_ftp_snapshot,
            )
            await self.ride_repo.update_ride_metadata(
                str(ride_id),
                {
                    **{
                        key: value
                        for key, value in frozen_economic_fields.items()
                        if key.startswith("threshold_") or key == "effort_spans_ms"
                    },
                    "canonical_match": preliminary_attestation.canonical_match,
                    **(
                        {"import_diagnostics": {
                            **((ride_row or {}).get("import_diagnostics") or {}),
                            "idle_recording_evidence": idle_evidence.as_dict(),
                        }}
                        if idle_evidence is not None else {}
                    ),
                    **(
                        {"review_reason": idle_evidence.review_reason}
                        if idle_evidence is not None and idle_evidence.review_reason
                        else {}
                    ),
                },
            )
            threshold_candidate = await register_threshold_effort(
                self.ride_repo,
                ride_id=ride_id,
                evidence=threshold_evidence,
            )
            threshold_review_reason = threshold_candidate_review_reason(
                threshold_candidate
            )
            metrics, threshold_training_fields = (
                await self.analytics_service.calculate_threshold_ride_metrics(
                    user_id=str(user_id),
                    parsed_ride=parsed_ride,
                    user_weight_kg=user_weight_kg,
                    initial_metrics=metrics,
                    metrics_calculator=self.ride_attester.calculate_metrics,
                )
            )
            if preliminary_attestation.requires_review:
                logger.warning(
                    "[RideProcessor] Preliminary attestation mismatch; "
                    f"ride={ride_id} reason={preliminary_attestation.review_reason} "
                    f"preliminary_hash={preliminary_attestation.preliminary_ride_hash_hex} "
                    f"canonical_hash={onchain_ride_identity.ride_hash.hex()}"
                )

            # Capture user profile snapshot before any metrics computation
            user_wallet_for_snapshot = await self.user_repo.get_user_wallet(user_id)
            if user_wallet_for_snapshot and (ride_row or {}).get("reward_ftp_w") is None:
                await self.ride_projection_store.capture_profile_snapshot(
                    wallet=user_wallet_for_snapshot,
                    ride_id=ride_id,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=threshold_training_fields.get(
                        "threshold_training_w"
                    ),
                    reward_ftp_snapshot=reward_ftp_snapshot,
                )

            logger.info(f"[RideProcessor] Parsed: {len(parsed_ride.records)} records, {len(parsed_ride.gps_track)} GPS points")
            logger.info(f"[RideProcessor] Metrics: duration={metrics.duration_sec}s, distance={metrics.distance_m}m")

            # Publish NATS event: metrics computed
            try:
                user_wallet_nats = await self.user_repo.get_user_wallet(user_id)
                await self._publish_nats_event("rides.events.metrics_ready", {
                    "ride_id": str(ride_id),
                    "wallet": user_wallet_nats,
                    "tss": metrics.tss,
                    "normalized_power_w": metrics.normalized_power_w,
                    "duration_s": metrics.duration_sec,
                    "distance_m": metrics.distance_m,
                })
            except Exception:
                pass  # Best-effort, never block ride processing

            logger.info("[RideProcessor] Storing activity streams...")
            await self.ride_projection_store.store_activity_streams(ride_id, parsed_ride)
            logger.info("[RideProcessor] Activity streams stored")

            logger.info("[RideProcessor] Converting GPS track...")
            gps_track = self.ride_projection_store.gps_track_to_dicts(
                parsed_ride.gps_track
            )
            if gps_track:
                logger.info(f"[RideProcessor] Storing {len(gps_track)} GPS points...")
                await self.ride_repo.store_gps_points(ride_id, gps_track)
                logger.info("[RideProcessor] GPS points stored")

            canon_evidence = (
                self.ride_projection_store.build_canon_traversal_evidence(
                    ride_id=ride_id,
                    ride_hash_hex=onchain_ride_identity.ride_hash.hex(),
                    ride_parser_version=onchain_ride_identity.parser_version,
                    parsed_ride=parsed_ride,
                )
            )
            await self.ride_projection_store.store_canon_traversal_evidence(
                canon_evidence
            )

            # Project GPS coordinates to H3 tiles and store tile samples
            logger.info("[RideProcessor] Processing tile projection...")
            tile_samples_count = 0
            tiles_explored = 0
            tile_samples = []
            raw_climb_samples = canon_evidence.raw_samples()
            detector_climb_samples = detector_compatible_samples(raw_climb_samples)
            record_points = canon_evidence.record_points(parsed_ride.started_at)
            if record_points:
                logger.info(f"[RideProcessor] Projecting {len(record_points)} points to H3 tiles...")
                tile_samples_count, tiles_explored, tile_samples = await self.ride_projection_store.process_tile_projection(
                    ride_id=ride_id,
                    user_id=user_id,
                    points=record_points,
                    ride_start_time=parsed_ride.started_at,
                )
                logger.info(f"[RideProcessor] Tile projection complete: {tiles_explored} tiles, {tile_samples_count} samples")

            # Get user wallet for CAL processing
            user_wallet = await self.user_repo.get_user_wallet(user_id)

            economic_tss_write = (
                {"economic_tss": economic_tss}
                if (ride_row or {}).get("economic_tss") is None
                else {}
            )
            await self.ride_repo.update_ride_status(
                ride_id,
                "processing",
                normalized_power_raw_w=getattr(
                    economic_metrics, "normalized_power_raw_w", None
                ),
                normalized_power_duration_s=(
                    getattr(economic_metrics, "normalized_power_duration_s", None)
                    if getattr(economic_metrics, "normalized_power_raw_w", None)
                    is not None
                    else None
                ),
                tss=metrics.tss,
                **threshold_training_fields,
                **economic_tss_write,
            )
            # The frozen whole-file TSS remains the untrimmed pricing authority.
            economic_metrics = copy(economic_metrics)
            economic_metrics.tss = economic_tss
            effort_policy = _frozen_ride_effort_policy(ride_row)
            if effort_policy is None:
                admission_effort_policy = build_ride_effort_policy(
                    economic_metrics,
                    blocking_review_reason=(
                        preliminary_attestation.review_reason
                        if preliminary_attestation.requires_review
                        else threshold_review_reason or (
                            idle_evidence.review_reason if idle_evidence is not None else None
                        )
                    ),
                    completed_at=parsed_ride.completed_at,
                    started_at=parsed_ride.started_at,
                )
                effort_policy = project_threshold_hold_policy(
                    admission_effort_policy,
                    reward_ftp_snapshot,
                )
            else:
                admission_effort_policy = build_ride_effort_policy(
                    economic_metrics,
                    blocking_review_reason=effort_policy.review_reason,
                    completed_at=parsed_ride.completed_at,
                    started_at=parsed_ride.started_at,
                )
            plan_effort_policy = _snapshot_file_policy(_frozen_ride_effort_policy(ride_row), economic_tss, admission_effort_policy)
            ride_cal_earned = effort_policy.rewardable_cal
            economic_review_reason = effort_policy.review_reason
            requires_economic_review = effort_policy.requires_economic_review
            if not user_wallet and not requires_economic_review:
                requires_economic_review = True
                economic_review_reason = MISSING_WALLET_ECONOMIC_REVIEW_REASON
            if economic_review_reason:
                logger.info(
                    "[RideProcessor] Economic abstention for ride %s: %s "
                    "(tss=%.1f, avg_power=%s, normalized_power=%s, avg_hr=%s)",
                    ride_id,
                    economic_review_reason,
                    economic_tss,
                    getattr(metrics, "avg_power_w", None),
                    getattr(metrics, "normalized_power_w", None),
                    getattr(metrics, "avg_hr_bpm", None),
                )
            total_ride_duration_s = (
                getattr(metrics, "moving_time_sec", 0) or metrics.duration_sec or 0
            )

            # Detect patterns from tile samples (Climb, Steady, Exploration)
            # This also distributes CAL to vaults crossed during the ride
            logger.info("[RideProcessor] Detecting patterns...")
            pattern_results: Optional[PatternResults] = None
            device_name = getattr(parsed_ride, "device_name", None)
            if tile_samples:
                pattern_results = await self.ride_enrichment_service.detect_and_store_patterns(
                    ride_id=ride_id,
                    user_id=user_id,
                    tile_samples=tile_samples,
                    raw_climb_samples=raw_climb_samples,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=threshold_training_fields.get(
                        "threshold_training_w"
                    ),
                    ride_start_time=parsed_ride.started_at,
                    completed_at=parsed_ride.completed_at,
                    cal_earned=0,
                    total_ride_duration_s=total_ride_duration_s,
                    apply_vault_economics=False,
                )

            # Store sensor integrity on the ride
            if pattern_results and pattern_results.sensor_integrity:
                try:
                    await self.ride_repo.update_ride_metadata(
                        ride_id=str(ride_id),
                        updates={"sensor_integrity": pattern_results.sensor_integrity.to_dict()},
                    )
                except Exception as e:
                    logger.warning(f"[RideProcessor] Failed to store sensor integrity: {e}")

            # Publish NATS event: ride enriched with patterns/vaults
            try:
                _enrich_wallet = user_wallet_nats if 'user_wallet_nats' in dir() else await self.user_repo.get_user_wallet(user_id)
                await self._publish_nats_event("rides.events.enriched", {
                    "ride_id": str(ride_id),
                    "wallet": _enrich_wallet,
                    "climbs_count": len(pattern_results.climb_patterns) if pattern_results else 0,
                    "tiles_explored": tiles_explored,
                    "tile_samples_count": tile_samples_count,
                })
            except Exception:
                pass  # Best-effort, never block ride processing

            # Note: Segment matching has been replaced by pattern detection above
            # Patterns (Climb, Steady, Exploration) are the new competition primitives

            achievements = await self.achievement_detector.detect_achievements(
                user_id=user_id,
                ride_id=ride_id,
                metrics=metrics,
                pattern_results=pattern_results,
                user_repo=self.user_repo,
                achievement_repo=self.achievement_repo,
            )

            async def load_native_activity():
                return parsed_ride

            trim = None
            vault_allocs: List[Dict[str, Any]] = []
            ride_attestation_ref = None
            ride_attestation_pda = None
            ride_attestation_tx_signature = None
            ride_attested_at = None
            economic_outcome: Optional[RideEconomicOutcome] = None
            economic_durable_checkpoint = True
            if user_wallet and not requires_economic_review:
                frozen_plan, vault_allocs, paid_policy, trim = await self._freeze_ride_economic_plan(
                    ride_id=ride_id,
                    user_id=user_id,
                    user_wallet=user_wallet,
                    identity=onchain_ride_identity,
                    effort_policy=plan_effort_policy,
                    economic_metrics=economic_metrics,
                    started_at=parsed_ride.started_at,
                    completed_at=parsed_ride.completed_at,
                    total_tss=int(economic_tss),
                    total_distance_m=int(metrics.distance_m or 0),
                    total_vert_m=int(metrics.elevation_gain_m or 0),
                    total_ride_duration_s=int(total_ride_duration_s),
                    reward_ftp_snapshot=reward_ftp_snapshot,
                    pattern_results=pattern_results,
                    tile_samples=tile_samples,
                    raw_climb_samples=detector_climb_samples,
                    # A resumed ride carries its whole-file idle decision in the
                    # frozen review reason; do not re-derive it from a new parse.
                    file_idle_reason=(
                        idle_evidence.review_reason if idle_evidence is not None else None
                    ) or "",
                    effort_spans_ms=(ride_row or {}).get("effort_spans_ms") or effort_spans_ms_rust(parsed_ride),
                    load_native_activity=load_native_activity,
                )

                effort_policy = project_threshold_hold_policy(paid_policy, reward_ftp_snapshot)
                ride_cal_earned = effort_policy.rewardable_cal
                requires_economic_review = effort_policy.requires_economic_review
                economic_review_reason = effort_policy.review_reason
                await self.ride_repo.update_ride_metadata(str(ride_id), {
                    **effort_policy.as_ride_fields(), **(trim.projections() if trim else {}),
                })

            if pattern_results:
                await self.ride_projection_store.store_pattern_results(pattern_results)

            # DUNG minting: only via epoch distribution (vault pot), not per-ride
            dung_minted = 0
            tx_signature = ride_attestation_ref

            if user_wallet and not requires_economic_review:
                economic_outcome = await self.ride_economic_coordinator.execute(ride_id)
                economic_durable_checkpoint = economic_outcome.durable_checkpoint
                if economic_outcome.status == "recovery_pending":
                    return {
                        "status": "recovery_pending",
                        "ride_id": str(ride_id),
                        "durable_checkpoint": economic_outcome.durable_checkpoint,
                        "economic_state": economic_outcome.state,
                        "error": economic_outcome.error,
                    }
                if economic_outcome.status == "under_review":
                    requires_economic_review = True
                    economic_review_reason = (
                        economic_review_reason
                        or economic_outcome.error
                        or "ride_economic_review"
                    )
                else:
                    ride_attestation_pda = economic_outcome.ride_attestation_pda
                    ride_attestation_tx_signature = (
                        economic_outcome.ride_attestation_tx_signature
                    )
                    ride_attested_at = economic_outcome.ride_attested_at
                    ride_attestation_ref = (
                        economic_outcome.ride_attestation_tx_signature
                    )
                    tx_signature = (
                        economic_outcome.cal_tx_signature
                        or economic_outcome.ride_attestation_tx_signature
                    )
            elif requires_economic_review:
                logger.info(
                    f"[RideProcessor] Skipping CAL credit for ride {ride_id} "
                    f"(review_reason={economic_review_reason})"
                )

            progression_snapshot = {
                "total_tss_after": None,
                "level_delta": None,
                "level_after": None,
            }
            if not requires_economic_review:
                counted_economic_tss = (
                    0.0
                    if effort_policy.reward_policy
                    == THRESHOLD_PROVISIONAL_HOLD_POLICY
                    else economic_tss
                )
                progression_snapshot = await _build_progression_snapshot(
                    user_repo=self.user_repo,
                    user_id=user_id,
                    ride_tss=counted_economic_tss,
                    current_ride_prior_tss=_safe_float(
                        (
                            (ride_row or {}).get("economic_tss")
                            if (ride_row or {}).get("economic_tss") is not None
                            else (ride_row or {}).get("tss")
                        )
                        if isinstance(ride_row, dict)
                        else None
                    ),
                )

            # Device testimony (FIT evidence pass): provenance held at full
            # fidelity for personhood; the Session claim stored beside our
            # recomputation and the event clock as a divergence tripwire.
            # Economics keep the frozen gap-derived moving time until the
            # corpus comparison ratifies the event clock.
            evidence_updates: dict = {}
            provenance = getattr(parsed_ride, "device_provenance", None)
            if provenance:
                evidence_updates["device_provenance"] = provenance
            laps = getattr(parsed_ride, "laps", None)
            if laps and len(laps) >= 2:
                # A single lap is the whole ride; only real segmentation is
                # worth carrying.
                evidence_updates["laps"] = laps
            balance = getattr(parsed_ride, "power_balance", None)
            if balance:
                evidence_updates["power_balance"] = balance
            device_summary = getattr(parsed_ride, "device_summary", None)
            event_moving = getattr(parsed_ride, "event_moving_time_s", None)
            pause_count = getattr(parsed_ride, "timer_pause_count", 0)
            if device_summary or event_moving is not None:
                recomputed_moving = getattr(metrics, "moving_time_s", None)
                recomputed_distance = getattr(metrics, "distance_m", None)
                tripwire = {
                    "claimed": device_summary,
                    "event_moving_time_s": event_moving,
                    "timer_pause_count": pause_count,
                    "recomputed_moving_time_s": recomputed_moving,
                    "recomputed_distance_m": recomputed_distance,
                    "gps_accuracy": getattr(parsed_ride, "gps_accuracy_stats", None),
                }
                claimed_timer = (device_summary or {}).get("total_timer_time_s")
                if claimed_timer and recomputed_moving:
                    divergence = abs(recomputed_moving - claimed_timer) / max(claimed_timer, 1)
                    tripwire["moving_time_divergence_pct"] = round(divergence * 100, 2)
                    if divergence > 0.05:
                        logger.warning(
                            "[RideProcessor] moving-time tripwire for %s: "
                            "recomputed %ss vs device claim %ss (%.1f%%)",
                            ride_id,
                            recomputed_moving,
                            claimed_timer,
                            divergence * 100,
                        )
                evidence_updates["device_summary"] = tripwire
            if evidence_updates:
                try:
                    await self.ride_repo.update_ride_metadata(ride_id, evidence_updates)
                except Exception as exc:
                    logger.info(
                        "[RideProcessor] device evidence write skipped for %s: %s",
                        ride_id,
                        exc,
                    )

            await capture_ride_weather(self.ride_repo, ride_id, parsed_ride)

            final_status = "under_review" if requires_economic_review else "completed"
            await self.ride_projection_store.update_ride_complete(
                ride_id=ride_id,
                status=final_status,
                metrics=metrics,
                parsed_ride=parsed_ride,
                dung_minted=dung_minted,
                tx_signature=tx_signature,
                cal_earned=0 if requires_economic_review else ride_cal_earned,
                ride_hash_hex=onchain_ride_identity.ride_hash.hex(),
                attestation_commitment_hex=onchain_ride_identity.attestation_commitment.hex(),
                ride_parser_version=onchain_ride_identity.parser_version,
                preliminary_ride_hash_hex=preliminary_attestation.preliminary_ride_hash_hex,
                preliminary_parser_version=preliminary_attestation.preliminary_parser_version,
                canonical_match=preliminary_attestation.canonical_match,
                review_reason=economic_review_reason,
                ride_attestation_pda=ride_attestation_pda,
                ride_attestation_tx_signature=ride_attestation_tx_signature,
                ride_attested_at=ride_attested_at,
                effort_policy=effort_policy,
                economic_tss=(
                    economic_tss
                    if (ride_row or {}).get("economic_tss") is None
                    else None
                ),
                reward_ftp_snapshot=(
                    reward_ftp_snapshot
                    if (ride_row or {}).get("reward_ftp_w") is None
                    else None
                ),
                **progression_snapshot,
            )

            if economic_outcome and economic_outcome.status == "complete":
                terminal_outcome = await self.ride_economic_terminal_projector.project(
                    ride_id
                )
                economic_durable_checkpoint = terminal_outcome.durable_checkpoint
                if terminal_outcome.status == "recovery_pending":
                    return {
                        "status": "recovery_pending",
                        "ride_id": str(ride_id),
                        "durable_checkpoint": terminal_outcome.durable_checkpoint,
                        "economic_state": "complete",
                        "error": terminal_outcome.error,
                    }
                ride_cal_earned = terminal_outcome.cal_earned

            ride_date = parsed_ride.started_at.date() if parsed_ride.started_at else datetime.utcnow().date()
            await self.analytics_service.update_daily_aggregates(
                user_id=str(user_id),
                ride_date=ride_date,
            )

            # Publish NATS event: ride processing completed
            _complete_wallet = user_wallet
            try:
                _complete_wallet = _complete_wallet or (await self.user_repo.get_user_wallet(user_id))
                await self._publish_nats_event("rides.events.completed", {
                    "ride_id": str(ride_id),
                    "wallet": _complete_wallet,
                    "tss": metrics.tss,
                    "cal_earned": 0 if requires_economic_review else ride_cal_earned,
                    "estimated_cal": effort_policy.estimated_cal,
                    "reward_policy": effort_policy.reward_policy,
                    "patterns_count": pattern_results.total_patterns if pattern_results else 0,
                    "achievements_count": len(achievements),
                })
            except Exception:
                pass  # Best-effort, never block ride processing

            return {
                "status": final_status,
                "metrics": metrics.to_dict() if hasattr(metrics, "to_dict") else metrics.__dict__,
                "achievements": len(achievements),
                "patterns": pattern_results.total_patterns if pattern_results else 0,
                "pattern_summary": pattern_results.summary() if pattern_results else None,
                # Token rewards
                "dung_reward": dung_minted,
                "tx_signature": tx_signature,
                "cal_earned": 0 if requires_economic_review else ride_cal_earned,
                "estimated_cal": effort_policy.estimated_cal,
                "reward_policy": effort_policy.reward_policy,
                "effort_evidence_tier": effort_policy.effort_evidence_tier,
                "durable_checkpoint": economic_durable_checkpoint,
                "economic_state": (
                    economic_outcome.state
                    if economic_outcome
                    else ("review" if requires_economic_review else "not_applicable")
                ),
            }
        except Exception as exc:
            await self.ride_repo.update_ride_status(ride_id, "failed", error_message=str(exc))
            await self._emit_ride_failed_notification(
                ride_id=ride_id,
                user_id=user_id,
                phase="legacy_processing",
                message=str(exc),
            )
            raise

    # =========================================================================
    # Multi-Phase Processing (Strava-style progressive loading)
    # =========================================================================

    async def process_phase1_core(
        self,
        ride_id: UUID,
        file_data_b64: str,
        file_type: str,
        user_id: UUID,
        user_weight_kg: float = 75.0,
        user_ftp_w: int = 200,
        file_bytes: Optional[bytes] = None,
    ) -> Dict[str, Any]:
        """
        Phase 1: Core Processing (Target: <5 seconds)

        - Parse file (FIT/GPX/TCX)
        - Calculate metrics (TSS, NP, IF, distance, elevation, kcals)
        - Store activity streams
        - Store GPS track
        - Set status = metrics_ready

        User can now see their ride with map + basic stats.

        Args:
            file_bytes: Optional raw file bytes. If provided, skips base64 decode.

        Returns:
            Dict with metrics, parsed_ride data for subsequent phases
        """
        start_time = time.perf_counter()

        try:
            logger.info(f"[Phase1] Starting core processing for ride {ride_id}")
            await self.ride_repo.update_ride_status(ride_id, "processing")

            ride_row = await self.ride_repo.get_ride(str(ride_id))
            # Parse, metric calculation, and canonical identity are Attester
            # responsibilities: they define the reproducible ride facts that
            # later execution and projection consume.
            attested_ride = self.ride_attester.prepare_ride(
                file_data_b64=file_data_b64,
                file_type=file_type,
                file_bytes=file_bytes,
                ride_row=ride_row,
                user_weight_kg=user_weight_kg,
                user_ftp_w=user_ftp_w,
                reward_ftp_w=DEFAULT_REWARD_FTP_W,
            )
            onchain_ride_identity = attested_ride.onchain_identity
            preliminary_attestation = attested_ride.preliminary_check
            parsed_ride = attested_ride.parsed_ride
            threshold_evidence = threshold_effort_evidence_or_empty(parsed_ride)
            reward_ftp_snapshot = await self._bind_reward_ftp_snapshot(
                ride_id=ride_id,
                activity_started_at=parsed_ride.started_at,
            )
            logger.info(f"[Phase1] Parsed: {len(parsed_ride.records)} records, {len(parsed_ride.gps_track)} GPS points")

            metrics = attested_ride.metrics
            economic_metrics = attested_ride.economic_metrics or metrics
            if reward_ftp_snapshot.ftp_w != attested_ride.reward_ftp_w:
                economic_metrics = self.ride_attester.calculate_metrics(
                    parsed_ride=parsed_ride,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=reward_ftp_snapshot.ftp_w,
                )
            economic_tss = float(
                (ride_row or {}).get("economic_tss")
                if (ride_row or {}).get("economic_tss") is not None
                else economic_metrics.tss or 0
            )
            idle_evidence = (
                assess_idle_recording(parsed_ride.records)
                if (ride_row or {}).get("economic_tss") is None
                else None
            )
            frozen_economic_fields = _unfrozen_ride_economic_fields(
                ride_row,
                threshold_source_fields=threshold_evidence.source.as_ride_fields(),
                effort_spans_ms=effort_spans_ms_rust(parsed_ride),
                economic_tss=economic_tss,
                reward_ftp_snapshot=reward_ftp_snapshot,
            )
            await self.ride_repo.update_ride_metadata(
                str(ride_id),
                {
                    **{
                        key: value
                        for key, value in frozen_economic_fields.items()
                        if key.startswith("threshold_") or key == "effort_spans_ms"
                    },
                    "canonical_match": preliminary_attestation.canonical_match,
                    **(
                        {"import_diagnostics": {
                            **((ride_row or {}).get("import_diagnostics") or {}),
                            "idle_recording_evidence": idle_evidence.as_dict(),
                        }}
                        if idle_evidence is not None else {}
                    ),
                    **(
                        {"review_reason": idle_evidence.review_reason}
                        if idle_evidence is not None and idle_evidence.review_reason
                        else {}
                    ),
                },
            )
            threshold_candidate = await register_threshold_effort(
                self.ride_repo,
                ride_id=ride_id,
                evidence=threshold_evidence,
            )
            threshold_review_reason = threshold_candidate_review_reason(
                threshold_candidate
            )
            metrics, threshold_training_fields = (
                await self.analytics_service.calculate_threshold_ride_metrics(
                    user_id=str(user_id),
                    parsed_ride=parsed_ride,
                    user_weight_kg=user_weight_kg,
                    initial_metrics=metrics,
                    metrics_calculator=self.ride_attester.calculate_metrics,
                )
            )
            user_wallet_for_snapshot = await self.user_repo.get_user_wallet(user_id)
            if user_wallet_for_snapshot and (ride_row or {}).get("reward_ftp_w") is None:
                await self.ride_projection_store.capture_profile_snapshot(
                    wallet=user_wallet_for_snapshot,
                    ride_id=ride_id,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=threshold_training_fields.get(
                        "threshold_training_w"
                    ),
                    reward_ftp_snapshot=reward_ftp_snapshot,
                )
            effort_policy = _frozen_ride_effort_policy(ride_row)
            if effort_policy is None:
                admission_effort_policy = build_ride_effort_policy(
                    economic_metrics,
                    blocking_review_reason=(
                        preliminary_attestation.review_reason
                        if preliminary_attestation.requires_review
                        else threshold_review_reason or (
                            idle_evidence.review_reason if idle_evidence is not None else None
                        )
                    ),
                    completed_at=parsed_ride.completed_at,
                    started_at=parsed_ride.started_at,
                )
                effort_policy = project_threshold_hold_policy(
                    admission_effort_policy,
                    reward_ftp_snapshot,
                )
            logger.info(f"[Phase1] Metrics: duration={metrics.duration_sec}s, distance={metrics.distance_m}m, tss={metrics.tss}")

            # Store activity streams
            logger.info("[Phase1] Storing activity streams...")
            await self.ride_projection_store.store_activity_streams(ride_id, parsed_ride)

            # Store GPS track
            gps_track = self.ride_projection_store.gps_track_to_dicts(
                parsed_ride.gps_track
            )
            if gps_track:
                logger.info(f"[Phase1] Storing {len(gps_track)} GPS points...")
                await self.ride_repo.store_gps_points(ride_id, gps_track)

            canon_evidence = (
                self.ride_projection_store.build_canon_traversal_evidence(
                    ride_id=ride_id,
                    ride_hash_hex=onchain_ride_identity.ride_hash.hex(),
                    ride_parser_version=onchain_ride_identity.parser_version,
                    parsed_ride=parsed_ride,
                )
            )
            await self.ride_projection_store.store_canon_traversal_evidence(
                canon_evidence
            )

            # DEM elevation correction (boulderroller-v2-odmi6.2.1):
            # projection-only read model; never touches elevation_gain_m. A
            # failure here must never fail Phase 1 — columns stay NULL
            # ("never attempted") rather than faking an abstention.
            elevation_correction_fields: Dict[str, Any] = {}
            try:
                correction = correct_route_elevation(
                    route_points_from_gps_dicts(gps_track),
                    load_dem_grid(),
                )
                elevation_correction_fields = correction.as_ride_fields()
                logger.info(
                    "[Phase1] Elevation correction: status=%s coverage_bps=%s gain_m=%s",
                    correction.status,
                    correction.coverage_bps,
                    correction.elevation_gain_m,
                )
            except Exception:
                logger.exception("[Phase1] Elevation correction failed; leaving projection NULL")

            # Default ride title (boulderroller-v2-g0o24): set only when the
            # ride has no title yet; rider edits are never overwritten.
            title_fields: Dict[str, Any] = {}
            try:
                existing_title = (ride_row or {}).get("title")
                if not (isinstance(existing_title, str) and existing_title.strip()):
                    first_gps = gps_track[0] if gps_track else {}
                    title_fields["title"] = default_ride_title(
                        place_label_for_ride(ride_row or {}),
                        parsed_ride.started_at,
                        first_gps.get("latitude"),
                        first_gps.get("longitude"),
                    )
                    logger.info(
                        "[Phase1] Default ride title: %r", title_fields["title"]
                    )
            except Exception:
                logger.exception("[Phase1] Default title generation failed; leaving title NULL")

            # Calculate duration
            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Update ride with metrics and set status to metrics_ready
            await self.ride_repo.update_phase_status(
                ride_id=ride_id,
                phase=1,
                success=True,
                duration_ms=duration_ms,
                # Store metrics
                started_at=parsed_ride.started_at.isoformat() if parsed_ride.started_at else None,
                completed_at=parsed_ride.completed_at.isoformat() if parsed_ride.completed_at else None,
                duration_sec=metrics.duration_sec,
                moving_time_sec=getattr(metrics, "moving_time_sec", 0),
                metrics_version=getattr(metrics, "metrics_version", None),
                power_sample_count=getattr(metrics, "power_sample_count", 0),
                power_sample_coverage_bps=getattr(
                    metrics, "power_sample_coverage_bps", 0
                ),
                heart_rate_sample_count=getattr(
                    metrics, "heart_rate_sample_count", 0
                ),
                heart_rate_sample_coverage_bps=getattr(
                    metrics, "heart_rate_sample_coverage_bps", 0
                ),
                tss=metrics.tss,
                kcals=metrics.kcals,
                distance_m=metrics.distance_m,
                elevation_gain_m=metrics.elevation_gain_m,
                avg_power_w=metrics.avg_power_w,
                max_power_w=metrics.max_power_w,
                normalized_power_w=metrics.normalized_power_w,
                normalized_power_raw_w=getattr(
                    economic_metrics, "normalized_power_raw_w", None
                ),
                normalized_power_duration_s=(
                    getattr(economic_metrics, "normalized_power_duration_s", None)
                    if getattr(economic_metrics, "normalized_power_raw_w", None)
                    is not None
                    else None
                ),
                avg_hr_bpm=metrics.avg_hr_bpm,
                max_hr_bpm=metrics.max_hr_bpm,
                avg_speed_mps=metrics.avg_speed_mps,
                avg_cadence_rpm=metrics.avg_cadence_rpm,
                device_name=getattr(parsed_ride, "device_name", None),
                file_name=getattr(parsed_ride, "file_name", None),
                ride_hash_hex=onchain_ride_identity.ride_hash.hex(),
                attestation_commitment_hex=onchain_ride_identity.attestation_commitment.hex(),
                ride_parser_version=onchain_ride_identity.parser_version,
                preliminary_ride_hash_hex=preliminary_attestation.preliminary_ride_hash_hex,
                preliminary_parser_version=preliminary_attestation.preliminary_parser_version,
                canonical_match=preliminary_attestation.canonical_match,
                review_reason=effort_policy.review_reason,
                **threshold_training_fields,
                **frozen_economic_fields,
                **effort_policy.as_ride_fields(),
                **elevation_correction_fields,
                **title_fields,
            )

            logger.info(f"[Phase1] Completed in {duration_ms}ms - status=metrics_ready")

            # Publish NATS event: Phase 1 complete
            wallet = await self.user_repo.get_user_wallet(user_id)
            await self._publish_nats_event("rides.events.metrics_ready", {
                "ride_id": str(ride_id),
                "wallet": wallet,
                "tss": metrics.tss,
                "duration_s": metrics.duration_sec,
            })
            await capture_ride_weather(self.ride_repo, ride_id, parsed_ride)

            # Return data needed for Phase 2
            return {
                "status": "metrics_ready",
                "ride_id": str(ride_id),
                "user_id": str(user_id),
                "duration_ms": duration_ms,
                "metrics": metrics.to_dict() if hasattr(metrics, "to_dict") else metrics.__dict__,
                "effort_policy": effort_policy.as_ride_fields(),
                "ride_hash_hex": onchain_ride_identity.ride_hash.hex(),
                "canonical_match": preliminary_attestation.canonical_match,
                "review_reason": effort_policy.review_reason,
                "economic_tss": economic_tss,
                "reward_ftp_w": reward_ftp_snapshot.ftp_w,
                "reward_ftp_source": reward_ftp_snapshot.source,
                "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
                "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
                # Data for Phase 2
                "record_count": len(parsed_ride.records),
                "gps_point_count": len(gps_track),
                "started_at": parsed_ride.started_at.isoformat() if parsed_ride.started_at else None,
                # Store user params for Phase 2
                "user_weight_kg": user_weight_kg,
                "threshold_training_w": threshold_training_fields.get(
                    "threshold_training_w"
                ),
            }

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"[Phase1] Failed after {duration_ms}ms: {exc}")
            await self.ride_repo.update_phase_status(
                ride_id=ride_id,
                phase=1,
                success=False,
                error_message=str(exc),
                duration_ms=duration_ms,
            )
            await self._emit_ride_failed_notification(
                ride_id=ride_id,
                user_id=user_id,
                phase="phase1_core",
                message=str(exc),
            )
            raise

    async def process_phase2_enrichment(
        self,
        ride_id: UUID,
        user_id: UUID,
        user_weight_kg: float = 75.0,
        user_ftp_w: Optional[int] = None,
    ) -> Dict[str, Any]:
        """
        Phase 2: Enrichment (Target: 30-60 seconds)

        - Tile projection (H3)
        - Pattern detection (Climb, Steady, Exploration)
        - Vault signature matching
        - Leaderboard updates
        - Set status = enriched

        User now sees leaderboard positions fill in.

        Args:
            ride_id: Ride UUID
            user_id: User UUID
            user_weight_kg: User's weight for power calculations
            user_ftp_w: Retained task compatibility input; Threshold authority wins.

        Returns:
            Dict with patterns and enrichment data
        """
        start_time = time.perf_counter()
        phase2_step = "start"

        try:
            logger.info(f"[Phase2] Starting enrichment for ride {ride_id}")

            # Get ride data including metrics from Phase 1
            phase2_step = "load_ride"
            ride_data = await self.ride_repo.get_ride_for_phase2(str(ride_id))
            if not ride_data:
                raise ValueError(f"Ride {ride_id} not found")
            threshold_training_w = ride_data.get("threshold_training_w")
            if threshold_training_w is not None:
                threshold_training_w = int(threshold_training_w)

            if ride_data.get("processing_status") not in ("metrics_ready", "enriched", "completed"):
                logger.warning(f"[Phase2] Ride {ride_id} not ready for Phase 2 (status={ride_data.get('processing_status')})")
                raise ValueError(f"Ride not ready for Phase 2 processing")

            # Get parsed ride start time for tile projection
            phase2_step = "parse_ride_times"
            started_at_str = ride_data.get("started_at")
            ride_start_time = None
            if started_at_str:
                try:
                    ride_start_time = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    pass
            completed_at: Optional[datetime] = None
            completed_at_str = ride_data.get("completed_at")
            if completed_at_str:
                try:
                    completed_at = datetime.fromisoformat(completed_at_str.replace("Z", "+00:00"))
                except (ValueError, TypeError):
                    completed_at = None

            try:
                reward_ftp_snapshot = RewardFtpSnapshot.from_row(ride_data)
            except ValueError:
                reward_ftp_snapshot = await self._bind_reward_ftp_snapshot(
                    ride_id=ride_id,
                    activity_started_at=ride_start_time,
                )
                ride_data.update(
                    {
                        "reward_ftp_w": reward_ftp_snapshot.ftp_w,
                        "reward_ftp_source": reward_ftp_snapshot.source,
                        "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
                        "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
                    }
                )

            phase2_step = "load_canon_traversal_evidence"
            canon_evidence = None
            ride_hash_hex_for_evidence = ride_data.get("ride_hash_hex")
            parser_version_for_evidence = ride_data.get("ride_parser_version")
            if ride_hash_hex_for_evidence and parser_version_for_evidence is not None:
                canon_evidence = (
                    await self.ride_projection_store.load_canon_traversal_evidence(
                        ride_id=ride_id,
                        ride_hash_hex=str(ride_hash_hex_for_evidence),
                        ride_parser_version=int(parser_version_for_evidence),
                    )
                )

            canon_traversal_authoritative = canon_evidence is not None
            raw_climb_samples = (
                canon_evidence.raw_samples() if canon_evidence is not None else []
            )
            record_points = (
                canon_evidence.record_points(ride_start_time)
                if canon_evidence is not None
                else []
            )

            if canon_evidence is None:
                # Legacy rides retain the compressed route for display-oriented
                # detector enrichment, but D11 remains fail-closed until the raw
                # file is replayed through phase 1 to create exact evidence.
                logger.warning(
                    "[CanonTraversal] ride=%s has no identity-bound raw evidence; "
                    "exact canon traversal is disabled",
                    ride_id,
                )
                phase2_step = "load_legacy_gps_track"
                gps_points = await self.ride_repo.get_gps_track(ride_id) or []
                if not gps_points:
                    logger.warning(
                        f"[Phase2] No GPS points found for ride {ride_id}; "
                        "freezing a CAL-only economic plan"
                    )
                phase2_step = "build_sensor_lookup"
                sensor_lookup = await self.ride_projection_store.build_sensor_lookup(
                    ride_id
                )
                phase2_step = "assemble_legacy_record_points"
                for point in gps_points:
                    if (
                        point.get("latitude") is not None
                        and point.get("longitude") is not None
                    ):
                        ts = _coerce_phase2_timestamp(
                            point.get("timestamp"),
                            base_time=ride_start_time,
                        )
                        if ts is None:
                            continue
                        sensors = sensor_lookup(ts) if sensor_lookup else {}
                        record_points.append({
                            "timestamp": ts,
                            "lat": point["latitude"],
                            "lon": point["longitude"],
                            "elevation_m": point.get("elevation_m", point.get("elevation")),
                            "power_w": sensors.get("power"),
                            "hr_bpm": sensors.get("heart_rate"),
                            "speed_mps": sensors.get("speed"),
                        })

            phase2_step = "sort_record_points"
            record_points.sort(key=lambda p: p["timestamp"])

            # Process tile projection
            logger.info(f"[Phase2] Processing tile projection for {len(record_points)} points...")
            tile_samples_count = 0
            tiles_explored = 0
            tile_samples = []

            if record_points:
                phase2_step = "build_raw_climb_samples"
                if canon_evidence is None:
                    # Legacy-only detector input. It is explicitly barred from
                    # D11 by canon_traversal_authoritative=False below.
                    raw_climb_samples = [
                        {
                            "tile_id": sample.tile_id,
                            "t": float(sample.t),
                            "lat": sample.lat,
                            "lon": sample.lon,
                            "elevation_m": sample.elevation_m,
                            "power_w": sample.power_w,
                            "hr_bpm": sample.hr_bpm,
                            "speed_mps": sample.speed_mps,
                        }
                        for sample in self.tile_service.get_tile_sequence(
                            record_points,
                            resolution=10,
                            start_time=ride_start_time,
                        )
                    ]
                phase2_step = "project_tile_samples"
                tile_samples_count, tiles_explored, tile_samples = await self.ride_projection_store.process_tile_projection(
                    ride_id=ride_id,
                    user_id=user_id,
                    points=record_points,
                    ride_start_time=ride_start_time,
                )
                logger.info(f"[Phase2] Tile projection: {tiles_explored} tiles, {tile_samples_count} samples, {len(raw_climb_samples)} raw samples")

            detector_climb_samples = detector_compatible_samples(
                raw_climb_samples
            )

            trim = None
            native_cache = None
            async def load_native_activity():
                nonlocal native_cache
                if native_cache is not None:
                    return native_cache
                path = ride_data.get("raw_file_path")
                if not path:
                    raise PaidEffortEvidenceUnavailableError("raw ride file unavailable")
                try:
                    raw = await create_file_storage_service().download_ride_file(path)
                    attested = self.ride_attester.prepare_ride(
                        file_data_b64="", file_type=ride_data["file_type"], file_bytes=raw,
                        ride_row=ride_data, user_weight_kg=75.0, user_ftp_w=reward_ftp_snapshot.ftp_w,
                        reward_ftp_w=reward_ftp_snapshot.ftp_w,
                    )
                    identity = attested.onchain_identity
                    if identity.ride_hash.hex() != ride_data.get("ride_hash_hex") or identity.parser_version != ride_data.get("ride_parser_version"):
                        raise PaidEffortEvidenceMismatchError("native evidence does not match frozen ride identity")
                    native_cache = attested.parsed_ride
                except PaidEffortEvidenceMismatchError:
                    raise
                except (FileNotFoundError, ValueError) as exc:
                    raise PaidEffortEvidenceUnavailableError(str(exc)) from exc
                return native_cache

            phase2_step = "build_effort_policy"
            economic_metrics = _economic_metrics_source(ride_data)
            economic_tss = float(economic_metrics.get("tss") or 0)
            admission_effort_policy = build_ride_effort_policy(
                economic_metrics,
                blocking_review_reason=(
                    ride_data.get("review_reason")
                    or (
                        MISSING_ECONOMIC_TSS_REVIEW_REASON
                        if ride_data.get("economic_tss") is None
                        else None
                    )
                ),
            )
            frozen_effort_policy = _frozen_ride_effort_policy(ride_data)
            complete_frozen_policy = frozen_effort_policy is not None and all(
                ride_data.get(field) is not None
                for field in (
                    "effort_evidence_tier",
                    "reward_policy",
                    "estimated_cal",
                    "rewardable_cal",
                    "tributable_cal",
                )
            )
            effort_policy = (
                frozen_effort_policy
                if complete_frozen_policy
                else project_threshold_hold_policy(
                    admission_effort_policy,
                    reward_ftp_snapshot,
                )
            )
            plan_effort_policy = _snapshot_file_policy(frozen_effort_policy if complete_frozen_policy else None, economic_tss, admission_effort_policy)
            ride_cal_earned = effort_policy.rewardable_cal
            if effort_policy.review_reason:
                logger.info(
                    "[Phase2] Economic abstention for ride %s: %s "
                    "(tss=%.1f, avg_power=%s, normalized_power=%s, avg_hr=%s)",
                    ride_id,
                    effort_policy.review_reason,
                    economic_tss,
                    ride_data.get("avg_power_w"),
                    ride_data.get("normalized_power_w"),
                    ride_data.get("avg_hr_bpm"),
                )
            total_ride_duration_s = int(
                ride_data.get("moving_time_sec") or ride_data.get("duration_sec") or 0
            )
            ride_hash_hex = ride_data.get("ride_hash_hex")
            ride_hash: Optional[bytes] = None
            if ride_hash_hex:
                try:
                    ride_hash = bytes.fromhex(str(ride_hash_hex))
                except ValueError:
                    logger.warning(
                        "[Phase2] Invalid ride_hash for ride %s; vault display enrichment "
                        "will continue without reward side effects",
                        ride_id,
                    )
            if effort_policy.is_tributable and ride_hash is None:
                logger.info(
                    "[Phase2] Skipping vault reward side effects for ride %s: missing ride_hash",
                    ride_id,
                )

            # Detect patterns
            logger.info("[Phase2] Detecting patterns...")
            pattern_results: Optional[PatternResults] = None
            if tile_samples:
                phase2_step = "detect_and_store_patterns"
                pattern_results = await self.ride_enrichment_service.detect_and_store_patterns(
                    ride_id=ride_id,
                    user_id=user_id,
                    tile_samples=tile_samples,
                    raw_climb_samples=raw_climb_samples,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=threshold_training_w,
                    ride_start_time=ride_start_time,
                    completed_at=completed_at,
                    cal_earned=0,
                    total_ride_duration_s=total_ride_duration_s,
                    apply_vault_economics=False,
                    ride_hash=None,
                    canon_traversal_authoritative=canon_traversal_authoritative,
                )

            # Store sensor integrity on the ride
            phase2_step = "store_sensor_integrity"
            if pattern_results and pattern_results.sensor_integrity:
                try:
                    await self.ride_repo.update_ride_metadata(
                        ride_id=str(ride_id),
                        updates={"sensor_integrity": pattern_results.sensor_integrity.to_dict()},
                    )
                except Exception as e:
                    logger.warning(f"[Phase2] Failed to store sensor integrity: {e}")

            frozen_plan: Optional[Dict[str, Any]] = None
            economic_review_reason = effort_policy.review_reason
            requires_economic_review = (
                effort_policy.requires_economic_review
                or ride_data.get("canonical_match") is False
            )
            if not requires_economic_review:
                phase2_step = "freeze_ride_economic_plan"
                attestation_commitment_hex = ride_data.get(
                    "attestation_commitment_hex"
                )
                parser_version = ride_data.get("ride_parser_version")
                if (
                    ride_hash is None
                    or not attestation_commitment_hex
                    or parser_version is None
                    or ride_start_time is None
                    or completed_at is None
                ):
                    raise ValueError(
                        "accepted ride is missing canonical economic identity"
                    )
                wallet = await self.user_repo.get_user_wallet(user_id)
                if not wallet:
                    requires_economic_review = True
                    economic_review_reason = MISSING_WALLET_ECONOMIC_REVIEW_REASON
                else:
                    identity = OnchainRideIdentity(
                        ride_hash=ride_hash,
                        attestation_commitment=bytes.fromhex(
                            str(attestation_commitment_hex)
                        ),
                        parser_version=int(parser_version),
                        source_kind=_source_kind_from_file_type(
                            str(ride_data.get("file_type") or "")
                        ),
                    )
                    frozen_plan, _, paid_policy, trim = await self._freeze_ride_economic_plan(
                        ride_id=ride_id,
                        user_id=user_id,
                        user_wallet=wallet,
                        identity=identity,
                        effort_policy=plan_effort_policy,
                        economic_metrics=economic_metrics,
                        started_at=ride_start_time,
                        completed_at=completed_at,
                        total_tss=int(economic_tss),
                        total_distance_m=int(ride_data.get("distance_m") or 0),
                        total_vert_m=int(ride_data.get("elevation_gain_m") or 0),
                        total_ride_duration_s=total_ride_duration_s,
                        reward_ftp_snapshot=reward_ftp_snapshot,
                        pattern_results=pattern_results,
                        tile_samples=tile_samples,
                        raw_climb_samples=detector_climb_samples,
                        effort_spans_ms=ride_data.get("effort_spans_ms"),
                        load_native_activity=load_native_activity,
                    )

                    effort_policy = project_threshold_hold_policy(paid_policy, reward_ftp_snapshot)
                    ride_cal_earned = effort_policy.rewardable_cal
                    requires_economic_review = effort_policy.requires_economic_review
                    economic_review_reason = effort_policy.review_reason

            if pattern_results:
                phase2_step = "store_pattern_results_without_economics"
                await self.ride_projection_store.store_pattern_results(pattern_results)

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            # Update status to enriched
            phase2_step = "update_phase_success"
            await self.ride_repo.update_phase_status(
                ride_id=ride_id,
                phase=2,
                success=True,
                duration_ms=duration_ms,
                processing_status=(
                    "under_review" if requires_economic_review else "enriched"
                ),
                review_reason=economic_review_reason,
                cal_earned=0 if requires_economic_review else ride_cal_earned,
                **effort_policy.as_ride_fields(),
                **(trim.projections() if trim else {}),
            )

            logger.info(f"[Phase2] Completed in {duration_ms}ms - status=enriched")

            # Publish NATS event: Phase 2 complete
            phase2_step = "publish_enriched_event"
            wallet = await self.user_repo.get_user_wallet(user_id)
            climbs_count = len(pattern_results.climb_patterns) if pattern_results else 0
            vault_matches_count = len(pattern_results.vault_completions) if pattern_results else 0
            await self._publish_nats_event("rides.events.enriched", {
                "ride_id": str(ride_id),
                "wallet": wallet,
                "climbs_count": climbs_count,
                "vault_matches_count": vault_matches_count,
            })

            integrity = pattern_results.sensor_integrity if pattern_results else None
            return {
                "status": "enriched",
                "ride_id": str(ride_id),
                "user_id": str(user_id),
                "duration_ms": duration_ms,
                "tiles_explored": tiles_explored,
                "tile_samples_count": tile_samples_count,
                "patterns": pattern_results.total_patterns if pattern_results else 0,
                "pattern_summary": pattern_results.summary() if pattern_results else None,
                "cal_earned": 0 if requires_economic_review else ride_cal_earned,
                "estimated_cal": effort_policy.estimated_cal,
                "reward_policy": effort_policy.reward_policy,
                "effort_evidence_tier": effort_policy.effort_evidence_tier,
                "sensor_integrity_score": integrity.integrity_score if integrity else None,
                "economic_state": (
                    frozen_plan.get("state")
                    if frozen_plan
                    else ("review" if requires_economic_review else "not_applicable")
                ),
            }

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            phase2_error = f"{phase2_step}: {exc}"
            logger.error(f"[Phase2] Failed after {duration_ms}ms at {phase2_step}: {exc}", exc_info=True)
            # Other failures leave the ride retryable. A registry defect would
            # recur on every redelivery, so the ride fails visibly instead;
            # reprocessing it after the registry is repaired matches it.
            retryable = not isinstance(exc, CanonMatchingBlocked)
            await self.ride_repo.update_phase_status(
                ride_id=ride_id,
                phase=2,
                success=False,
                error_message=phase2_error,
                duration_ms=duration_ms,
                **({} if retryable else {"processing_status": "failed"}),
            )
            return {
                "status": "phase2_failed",
                "ride_id": str(ride_id),
                "error": phase2_error,
                "duration_ms": duration_ms,
                "retryable": retryable,
            }

    async def process_phase3_rewards(
        self,
        ride_id: UUID,
        user_id: UUID,
    ) -> Dict[str, Any]:
        """
        Phase 3: Rewards (Background)

        - Points/CAL calculation and awards
        - Achievement detection
        - On-chain operations (CAL credit, vault completion recording)
        - Set status = completed

        User sees points, achievements, tx signatures.

        Args:
            ride_id: Ride UUID
            user_id: User UUID

        Returns:
            Dict with rewards data
        """
        start_time = time.perf_counter()

        try:
            logger.info(f"[Phase3] Starting rewards for ride {ride_id}")

            # Get ride data
            ride_data = await self.ride_repo.get_ride_for_phase3(str(ride_id))
            if not ride_data:
                raise ValueError(f"Ride {ride_id} not found")

            economic_metrics = _economic_metrics_source(ride_data)
            economic_tss = float(economic_metrics.get("tss") or 0)
            frozen_plan = await self.ride_economic_repository.get_plan(ride_id)
            effort_policy: Optional[RideEffortPolicy] = None
            if frozen_plan is not None:
                user_wallet = str(frozen_plan["wallet"])
                ride_cal_earned = int(frozen_plan["exact_cal_base_units"]) // (
                    CAL_DECIMALS_MULTIPLIER
                )
                economic_review_reason = frozen_plan.get("review_reason")
                requires_economic_review = frozen_plan.get("state") == "review"
                estimated_cal = int(ride_data.get("estimated_cal") or ride_cal_earned)
                reward_policy = str(frozen_plan["reward_policy"])
                effort_evidence_tier = str(
                    ride_data.get("effort_evidence_tier") or "unknown"
                )
                effort_policy_fields: Dict[str, Any] = {}
            else:
                user_wallet = await self.user_repo.get_user_wallet(user_id)
                existing_review_reason = ride_data.get("review_reason")
                if (
                    existing_review_reason is None
                    and ride_data.get("economic_tss") is None
                ):
                    existing_review_reason = MISSING_ECONOMIC_TSS_REVIEW_REASON
                canonical_match = ride_data.get("canonical_match")
                effort_policy = build_ride_effort_policy(
                    economic_metrics,
                    blocking_review_reason=existing_review_reason,
                )
                ride_cal_earned = effort_policy.rewardable_cal
                economic_review_reason = effort_policy.review_reason
                requires_economic_review = (
                    bool(economic_review_reason) or canonical_match is False
                )
                if not user_wallet and not requires_economic_review:
                    requires_economic_review = True
                    economic_review_reason = MISSING_WALLET_ECONOMIC_REVIEW_REASON
                estimated_cal = effort_policy.estimated_cal
                reward_policy = effort_policy.reward_policy
                effort_evidence_tier = effort_policy.effort_evidence_tier
                effort_policy_fields = effort_policy.as_ride_fields()
            if economic_review_reason:
                logger.info(
                    "[Phase3] Economic abstention for ride %s: %s "
                    "(tss=%.1f, avg_power=%s, normalized_power=%s, avg_hr=%s)",
                    ride_id,
                    economic_review_reason,
                    economic_tss,
                    ride_data.get("avg_power_w"),
                    ride_data.get("normalized_power_w"),
                    ride_data.get("avg_hr_bpm"),
                )

            patterns = await self.ride_projection_store.get_pattern_results_from_db(
                ride_id
            )
            tx_signature = None
            dung_minted = 0
            ride_attestation_pda = ride_data.get("ride_attestation_pda")
            ride_attestation_tx_signature = ride_data.get("ride_attestation_tx_signature")
            ride_attested_at = ride_data.get("ride_attested_at")
            economic_outcome: Optional[RideEconomicOutcome] = None
            economic_durable_checkpoint = True

            if frozen_plan is not None:
                economic_outcome = await self.ride_economic_coordinator.execute(ride_id)
                economic_durable_checkpoint = economic_outcome.durable_checkpoint
                if economic_outcome.status == "recovery_pending":
                    duration_ms = int((time.perf_counter() - start_time) * 1000)
                    await self.ride_repo.update_phase_status(
                        ride_id=ride_id,
                        phase=3,
                        success=False,
                        error_message=economic_outcome.error,
                        duration_ms=duration_ms,
                    )
                    return {
                        "status": "recovery_pending",
                        "ride_id": str(ride_id),
                        "user_id": str(user_id),
                        "duration_ms": duration_ms,
                        "durable_checkpoint": economic_outcome.durable_checkpoint,
                        "economic_state": economic_outcome.state,
                        "error": economic_outcome.error,
                    }
                if economic_outcome.status == "under_review":
                    requires_economic_review = True
                    economic_review_reason = (
                        economic_review_reason
                        or economic_outcome.error
                        or "ride_economic_review"
                    )
                else:
                    ride_attestation_pda = economic_outcome.ride_attestation_pda
                    ride_attestation_tx_signature = (
                        economic_outcome.ride_attestation_tx_signature
                    )
                    ride_attested_at = economic_outcome.ride_attested_at
                    tx_signature = (
                        economic_outcome.cal_tx_signature
                        or economic_outcome.ride_attestation_tx_signature
                    )
            elif requires_economic_review:
                logger.info(
                    f"[Phase3] Skipping CAL credit for ride {ride_id}: "
                    f"review_reason={economic_review_reason}"
                )
            else:
                raise RuntimeError("accepted Phase 3 ride has no frozen economic plan")

            # Achievement detection
            logger.info("[Phase3] Detecting achievements...")
            # Need to get metrics and patterns for achievement detection
            metrics = RideMetrics(
                duration_sec=ride_data.get("duration_sec") or 0,
                distance_m=ride_data.get("distance_m") or 0,
                elevation_gain_m=ride_data.get("elevation_gain_m") or 0,
                tss=ride_data.get("tss") or 0,
                kcals=ride_data.get("kcals") or 0,
            )

            achievements = await self.achievement_detector.detect_achievements(
                user_id=user_id,
                ride_id=ride_id,
                metrics=metrics,
                pattern_results=patterns,
                user_repo=self.user_repo,
                achievement_repo=self.achievement_repo,
            )

            # Update daily aggregates
            started_at_str = ride_data.get("started_at")
            if started_at_str:
                try:
                    started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                    await self.analytics_service.update_daily_aggregates(
                        user_id=str(user_id),
                        ride_date=started_at.date(),
                    )
                except (ValueError, TypeError):
                    pass

            duration_ms = int((time.perf_counter() - start_time) * 1000)

            if economic_outcome and economic_outcome.status == "complete":
                terminal_outcome = await self.ride_economic_terminal_projector.project(
                    ride_id
                )
                economic_durable_checkpoint = terminal_outcome.durable_checkpoint
                if terminal_outcome.status == "recovery_pending":
                    await self.ride_repo.update_phase_status(
                        ride_id=ride_id,
                        phase=3,
                        success=False,
                        error_message=terminal_outcome.error,
                        duration_ms=duration_ms,
                    )
                    return {
                        "status": "recovery_pending",
                        "ride_id": str(ride_id),
                        "user_id": str(user_id),
                        "duration_ms": duration_ms,
                        "durable_checkpoint": terminal_outcome.durable_checkpoint,
                        "economic_state": "complete",
                        "error": terminal_outcome.error,
                    }
                ride_cal_earned = terminal_outcome.cal_earned
            else:
                await self.ride_repo.update_phase_status(
                    ride_id=ride_id,
                    phase=3,
                    success=True,
                    duration_ms=duration_ms,
                    processing_status="under_review",
                    review_reason=economic_review_reason,
                    cal_earned=0,
                    dung_minted=dung_minted,
                    tx_signature=tx_signature,
                    ride_attestation_pda=ride_attestation_pda,
                    ride_attestation_tx_signature=ride_attestation_tx_signature,
                    ride_attested_at=ride_attested_at,
                    **effort_policy_fields,
                )

            logger.info(
                f"[Phase3] Completed in {duration_ms}ms - "
                f"status={'under_review' if requires_economic_review else 'completed'}"
            )

            # Publish NATS event: Phase 3 complete
            await self._publish_nats_event("rides.events.completed", {
                "ride_id": str(ride_id),
                "wallet": user_wallet,
                "cal_earned": 0 if requires_economic_review else ride_cal_earned,
                "estimated_cal": estimated_cal,
                "reward_policy": reward_policy,
            })

            return {
                "status": "under_review" if requires_economic_review else "completed",
                "ride_id": str(ride_id),
                "user_id": str(user_id),
                "duration_ms": duration_ms,
                "cal_earned": 0 if requires_economic_review else ride_cal_earned,
                "estimated_cal": estimated_cal,
                "reward_policy": reward_policy,
                "effort_evidence_tier": effort_evidence_tier,
                "dung_minted": dung_minted,
                "tx_signature": tx_signature,
                "achievements": len(achievements),
                "durable_checkpoint": economic_durable_checkpoint,
                "economic_state": (
                    economic_outcome.state
                    if economic_outcome
                    else ("review" if requires_economic_review else "not_applicable")
                ),
            }

        except Exception as exc:
            duration_ms = int((time.perf_counter() - start_time) * 1000)
            logger.error(f"[Phase3] Failed after {duration_ms}ms: {exc}")
            await self.ride_repo.update_phase_status(
                ride_id=ride_id,
                phase=3,
                success=False,
                error_message=str(exc),
                duration_ms=duration_ms,
            )
            await self._emit_ride_failed_notification(
                ride_id=ride_id,
                user_id=user_id,
                phase="phase3_rewards",
                message=str(exc),
            )
            # Don't re-raise - Phase 3 failure shouldn't fail the ride
            return {
                "status": "phase3_failed",
                "ride_id": str(ride_id),
                "error": str(exc),
                "duration_ms": duration_ms,
            }
