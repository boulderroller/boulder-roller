"""Ride enrichment orchestration for tile-derived patterns."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Dict, List, Optional
from uuid import UUID

from ..repositories import TileRepository, UserRepository
from ..repositories.canon import CanonRegistryChanged, CanonRegistryError
from .canon_traversal import CanonTraversalEvaluation, CanonTraversalService
from .canon_traversal_evidence import detector_compatible_samples
from .climb_economy_processor import ClimbEconomyProcessor
from .pattern_engine import PatternEngine, PatternResults, UserProfile
from .ride_projection_store import RideProjectionStore
from .sample_time import (
    infer_sample_time_base,
    normalize_sample_times_to_seconds,
    sample_in_time_window,
    sample_time_seconds,
)
from .sensor_integrity import (
    compute_sensor_integrity,
    get_abstention_reasons_from_integrity,
    sample_has_valid_gps,
)
from .tile_service import TileAttributionService

logger = logging.getLogger(__name__)

_CANON_TRAVERSAL_REQUIRED_REASON = "MATCH:canon_traversal_required"
_NON_AUTHORITATIVE_CANON_TRACE_KEYS = (
    "registry_id",
    "canon_climb_id",
    "canon_id",
    "canon_version",
    "profile_hash",
    "canonical_profile_hash",
    "climb_pda",
    "vault_id",
    "vault_pda",
    "canon_binding_status",
)


class CanonMatchingBlocked(RuntimeError):
    """The ratified registry is malformed, so climb matching cannot run.

    A redelivery would read the same rows, so the ride fails here instead of
    retrying. Once the registry is repaired, reprocessing the ride matches it.
    """


class RideEnrichmentService:
    """Detect, enrich, and persist tile-derived ride patterns."""

    def __init__(
        self,
        *,
        user_repo: UserRepository,
        tile_repo: TileRepository,
        pattern_engine: PatternEngine,
        tile_attribution_service: TileAttributionService,
        climb_economy_processor: ClimbEconomyProcessor,
        ride_projection_store: RideProjectionStore,
        canon_traversal_service: Optional[CanonTraversalService] = None,
    ) -> None:
        self.user_repo = user_repo
        self.tile_repo = tile_repo
        self.pattern_engine = pattern_engine
        self.tile_attribution_service = tile_attribution_service
        self.climb_economy_processor = climb_economy_processor
        self.ride_projection_store = ride_projection_store
        self.canon_traversal_service = canon_traversal_service

    async def detect_and_store_patterns(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        tile_samples: List[Dict],
        raw_climb_samples: Optional[List[Dict]] = None,
        user_weight_kg: float = 75.0,
        user_ftp_w: Optional[int] = None,
        ride_start_time: Optional[datetime] = None,
        completed_at: Optional[datetime] = None,
        cal_earned: int = 0,
        total_ride_duration_s: int = 0,
        apply_vault_economics: bool = False,
        ride_hash: Optional[bytes] = None,
        canon_traversal_authoritative: bool = True,
    ) -> PatternResults:
        tile_samples = normalize_sample_times_to_seconds(
            tile_samples,
            base_time=ride_start_time,
            sort=True,
        )
        canon_raw_samples: Optional[List[Dict]] = None
        if raw_climb_samples is not None:
            # Preserve timed malformed GPS evidence for D11's corridor
            # denominator. The generic detector receives the sorted usable
            # projection below; exact canon receives this fail-closed stream.
            canon_raw_samples = normalize_sample_times_to_seconds(
                raw_climb_samples,
                base_time=ride_start_time,
                drop_untimed=False,
                sort=False,
            )
            raw_climb_samples = normalize_sample_times_to_seconds(
                raw_climb_samples,
                base_time=ride_start_time,
                sort=True,
            )
            raw_climb_samples = detector_compatible_samples(raw_climb_samples)

        user_wallet = await self.user_repo.get_user_wallet(user_id)
        if not user_wallet:
            logger.warning(f"No wallet found for user {user_id}, skipping patterns")
            return PatternResults(activity_id=ride_id, wallet="")

        user_profile = UserProfile(
            wallet=user_wallet,
            weight_kg=user_weight_kg,
            ftp_w=user_ftp_w,
            threshold_hr=None,
        )
        wallet_tile_history = await self.tile_repo.get_wallet_tile_history(user_wallet)

        results = await self.pattern_engine.detect_patterns(
            activity_id=ride_id,
            tile_samples=tile_samples,
            raw_climb_samples=raw_climb_samples,
            user_profile=user_profile,
            wallet_tile_history=wallet_tile_history,
            ride_start_time=ride_start_time,
        )

        # PatternEngine receives an integer, detector-compatible projection.
        # Canon authority and the persisted activity report must retain every
        # identity-bound sample, including malformed GPS rows in the coverage
        # denominator and exact fractional timestamps.
        if canon_raw_samples is not None:
            results.sensor_integrity = compute_sensor_integrity(canon_raw_samples)

        canon_evaluation: Optional[CanonTraversalEvaluation] = None
        if (
            canon_traversal_authoritative
            and self.canon_traversal_service is not None
            and canon_raw_samples
        ):
            try:
                canon_evaluation = await self.canon_traversal_service.evaluate_ride(
                    activity_id=ride_id,
                    wallet=user_wallet,
                    tile_samples=tile_samples,
                    raw_samples=canon_raw_samples,
                    user_weight_kg=user_weight_kg,
                )
            except CanonRegistryChanged:
                raise  # The registry moved mid-read; a redelivery reads it settled.
            except CanonRegistryError as exc:
                raise CanonMatchingBlocked(f"canon registry defect: {exc}") from exc
            self._reconcile_canon_traversals(results, canon_evaluation)
            for climb in canon_evaluation.climb_patterns:
                self._apply_canon_sensor_abstention(
                    climb,
                    canon_raw_samples,
                    results.sensor_integrity,
                )
            if canon_evaluation.attempts or canon_evaluation.rejections:
                logger.info(
                    "[CanonTraversal] ride=%s accepted=%d attempts=%d rejections=%s",
                    ride_id,
                    len(canon_evaluation.climb_patterns),
                    len(canon_evaluation.attempts),
                    canon_evaluation.rejections,
                )

        for climb in results.climb_patterns:
            if getattr(climb, "detector_version", None) != "canon_traversal_v1":
                self._mark_detector_discovery_only(climb)
        # PatternEngine's legacy detector matches are never Vault completion
        # authority after the D11 cutover, including rides without raw canon
        # evidence. Exact completion steps are built later from canon bindings.
        results.vault_completions = []

        if results.climb_patterns:
            detector_climbs = [
                climb
                for climb in results.climb_patterns
                if climb.detector_version != "canon_traversal_v1"
            ]
            await self._enrich_climbs_with_attribution(detector_climbs)
            self._score_climb_significance(results.climb_patterns)

        if apply_vault_economics:
            raise RuntimeError(
                "direct enrichment economics are disabled; freeze a ride economic plan"
            )

        results.vault_allocations = []

        logger.info(
            f"Detected {results.total_patterns} patterns for ride {ride_id}: "
            f"{results.summary()}"
        )
        return results

    @staticmethod
    def _reconcile_canon_traversals(
        results: PatternResults,
        evaluation: CanonTraversalEvaluation,
    ) -> None:
        retained_detector_climbs = [
            climb
            for climb in results.climb_patterns
            if not evaluation.overlaps_canon_coverage(
                climb.start_offset_s,
                climb.end_offset_s,
            )
        ]
        for climb in retained_detector_climbs:
            RideEnrichmentService._mark_detector_discovery_only(climb)
        # A detector completion is never authority after the D11 cutover. The
        # accepted canon traversal remains in climb_patterns so the exact
        # activation matcher can build any later completion step.
        results.vault_completions = []
        results.climb_patterns = sorted(
            retained_detector_climbs + list(evaluation.climb_patterns),
            key=lambda climb: (climb.start_offset_s, climb.end_offset_s, str(climb.id)),
        )

    @staticmethod
    def _mark_detector_discovery_only(climb: object) -> None:
        reasons = list(getattr(climb, "abstention_reasons", None) or [])
        if _CANON_TRAVERSAL_REQUIRED_REASON not in reasons:
            reasons.append(_CANON_TRAVERSAL_REQUIRED_REASON)
        climb.abstention_reasons = reasons
        climb.economic_eligible = False

        existing_trace = getattr(climb, "match_trace", None)
        trace = dict(existing_trace) if isinstance(existing_trace, dict) else {}
        non_authoritative_claim = dict(
            trace.get("non_authoritative_detector_claim") or {}
        )
        for key in _NON_AUTHORITATIVE_CANON_TRACE_KEYS:
            if key in trace:
                non_authoritative_claim[key] = trace.pop(key)
        if non_authoritative_claim:
            trace["non_authoritative_detector_claim"] = non_authoritative_claim
        # PatternEngine may have assembled a detector-era completion proposal
        # before D11 reconciliation. Persist no economic-action claim for that
        # detector result; only the exact canon binding path may add one later.
        trace["economic_action"] = None
        trace["authority"] = "discovery_only"
        trace["canon_traversal_required"] = True
        climb.match_trace = trace

    @staticmethod
    def _apply_canon_sensor_abstention(
        climb: object,
        samples: List[Dict],
        sensor_integrity: object,
    ) -> None:
        """Carry the shared activity and climb sensor gates onto D11 output."""
        reasons = list(getattr(climb, "abstention_reasons", None) or [])
        if sensor_integrity is not None:
            reasons.extend(get_abstention_reasons_from_integrity(sensor_integrity))
            if sensor_integrity.median_interval_s >= 30:
                reasons.append(
                    f"SENSOR:sparse_sampling_{sensor_integrity.median_interval_s:.0f}s"
                )

        start_t = getattr(climb, "start_offset_s", 0)
        end_t = getattr(climb, "end_offset_s", 0)
        sample_time_base = infer_sample_time_base(samples)
        climb_samples = [
            sample
            for sample in samples
            if sample_in_time_window(
                sample,
                start_t,
                end_t,
                base_time=sample_time_base,
            )
        ]
        if climb_samples:
            gps_count = sum(
                1
                for sample in climb_samples
                if sample_has_valid_gps(sample)
            )
            gps_coverage = gps_count / len(climb_samples)
            if gps_coverage < 0.50:
                reasons.append(f"CLIMB_SENSOR:gps_coverage_{gps_coverage:.0%}")

            elev_count = sum(
                1
                for sample in climb_samples
                if sample.get("elevation_m") is not None
            )
            elev_coverage = elev_count / len(climb_samples)
            if elev_coverage < 0.80:
                reasons.append(f"CLIMB_SENSOR:elev_coverage_{elev_coverage:.0%}")

            climb_sample_times = sorted(
                time_s
                for time_s in (
                    sample_time_seconds(
                        sample.get("t"),
                        base_time=sample_time_base,
                    )
                    for sample in climb_samples
                )
                if time_s is not None
            )
            for previous, current in zip(
                climb_sample_times,
                climb_sample_times[1:],
            ):
                gap = current - previous
                if gap > 300:
                    reasons.append(f"CLIMB_SENSOR:time_gap_{gap}s")
                    break

        time_s = getattr(climb, "time_s", 0)
        if time_s and time_s > 0:
            vam = (float(getattr(climb, "vert_m", 0)) / float(time_s)) * 3600
            if vam > 2000:
                reasons.append(f"CLIMB_SENSOR:high_vam_{vam:.0f}")

        climb.abstention_reasons = list(dict.fromkeys(reasons)) or None
        climb.economic_eligible = not bool(climb.abstention_reasons)

    async def _enrich_climbs_with_attribution(self, climb_patterns: List) -> None:
        for climb in climb_patterns:
            if not climb.tile_ids:
                continue
            try:
                attribution = await self.tile_attribution_service.get_climb_attribution(
                    tile_ids=climb.tile_ids,
                    vert_m=climb.vert_m,
                )
                climb.road_name = attribution.get("road_name")
                climb.road_grade = attribution.get("road_grade")
                climb.road_coverage_pct = attribution.get("coverage_pct")
                climb.attribution_summary = attribution.get("attribution_summary")
                if climb.road_name:
                    logger.info(
                        f"Climb attributed: {climb.vert_m:.0f}m on {climb.road_name}"
                    )
            except Exception as exc:
                logger.warning(f"Attribution failed for climb: {exc}")

    def _score_climb_significance(self, climb_patterns: List) -> None:
        from .terrain_bootstrap import score_climb

        scored = 0
        for climb in climb_patterns:
            persistence = getattr(climb, "persistence_m", None)
            if persistence is None:
                continue

            tile_ids = climb.tile_ids or []
            if not tile_ids:
                continue
            midpoint_tile = tile_ids[len(tile_ids) // 2]

            result = score_climb(persistence, midpoint_tile)
            if result is None:
                continue

            climb.significance_g = result.g_score
            climb.significance_percentile = result.percentile
            climb.significance_return_period = result.return_period
            climb.significance_confidence_tier = int(result.confidence_tier)
            climb.significance_bootstrapped = result.bootstrapped
            try:
                import h3

                climb.significance_cell_h3 = h3.cell_to_parent(midpoint_tile, 5)
            except Exception:
                climb.significance_cell_h3 = None
            scored += 1

        if scored > 0:
            logger.info(f"[Significance] Scored {scored}/{len(climb_patterns)} climbs")
