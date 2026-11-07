"""Ride read-model projection and persistence helpers.

This service owns backend-local persistence that is downstream of the
attested ride facts. It is intentionally not an Attester and not an Executor:
it stores streams, GPS points, phase status, pattern rows, profile snapshots,
and read-model reconstruction data used by the rider-facing app.
"""

from __future__ import annotations

import bisect
import logging
from datetime import datetime
from typing import Any, Callable, Dict, List, Optional
from uuid import UUID

from ..repositories import (
    PatternRepository,
    RideRepository,
    TileRepository,
    UserRepository,
)
from ..models.patterns import ClimbPattern, ExplorationPattern, SteadyPattern
from .pattern_engine import PatternResults
from .pattern_projection import pattern_from_row
from .canon_traversal_evidence import CANON_TRAVERSAL_EVIDENCE_VERSION, CanonTraversalEvidence
from .ride_attester import ParsedRide
from .ride_effort_policy import RideEffortPolicy
from .reward_ftp import RewardFtpSnapshot
from .ride_metrics import RideMetrics
from .tile_service import TileService

logger = logging.getLogger(__name__)


class RideProjectionStore:
    """Read-layer persistence for processed ride facts.

    The coordinator delegates here when it needs to persist derived facts or
    reconstruct read models. This class must not submit on-chain transactions
    and must not canonicalize ride files.
    """

    def __init__(
        self,
        *,
        ride_repo: RideRepository,
        tile_repo: TileRepository,
        pattern_repo: PatternRepository,
        user_repo: UserRepository,
        client: Any,
        tile_service: TileService,
    ) -> None:
        self.ride_repo = ride_repo
        self.tile_repo = tile_repo
        self.pattern_repo = pattern_repo
        self.user_repo = user_repo
        self._client = client
        self.tile_service = tile_service

    async def store_activity_streams(
        self,
        ride_id: UUID,
        parsed_ride: ParsedRide,
    ) -> None:
        """Extract and store time-series streams from parsed records."""
        streams: Dict[str, list] = {
            "power": [],
            "heart_rate": [],
            "cadence": [],
            "speed": [],
            "temperature": [],
        }
        timestamps: Dict[str, list[datetime]] = {k: [] for k in streams.keys()}

        for record in parsed_ride.records:
            ts = record.timestamp
            if record.power_w is not None:
                streams["power"].append(record.power_w)
                timestamps["power"].append(ts)
            if record.heart_rate_bpm is not None:
                streams["heart_rate"].append(record.heart_rate_bpm)
                timestamps["heart_rate"].append(ts)
            if record.cadence_rpm is not None:
                streams["cadence"].append(record.cadence_rpm)
                timestamps["cadence"].append(ts)
            if record.speed_mps is not None:
                streams["speed"].append(record.speed_mps)
                timestamps["speed"].append(ts)
            if getattr(record, "temperature_c", None) is not None:
                streams["temperature"].append(record.temperature_c)
                timestamps["temperature"].append(ts)

        for stream_type, values in streams.items():
            if values:
                await self.ride_repo.store_activity_stream(
                    ride_id=ride_id,
                    stream_type=stream_type,
                    timestamps=timestamps[stream_type],
                    values=values,
                )

    def gps_track_to_dicts(self, gps_track: List) -> List[Dict[str, Any]]:
        points = []
        for point in gps_track:
            if isinstance(point, dict):
                latitude = point.get("lat") or point.get("latitude")
                longitude = point.get("lon") or point.get("longitude")
                timestamp = point.get("timestamp")
                elevation = point.get("elevation_m")
                distance = point.get("distance_m")
            else:
                latitude = getattr(point, "lat", None)
                longitude = getattr(point, "lon", None)
                timestamp = getattr(point, "timestamp", None)
                elevation = getattr(point, "elevation_m", None)
                distance = getattr(point, "distance_m", None)

            if latitude is None or longitude is None or timestamp is None:
                continue

            points.append(
                {
                    "timestamp": timestamp,
                    "latitude": latitude,
                    "longitude": longitude,
                    "elevation": elevation,
                    "distance": distance,
                }
            )
        return points

    def records_to_dicts(self, records: List) -> List[Dict[str, Any]]:
        points: List[Dict[str, Any]] = []
        for rec in records:
            if isinstance(rec, dict):
                lat = rec.get("lat") or rec.get("latitude")
                lon = rec.get("lon") or rec.get("longitude")
                ts = rec.get("timestamp")
                elevation_m = rec.get("elevation_m", rec.get("elevation"))
                power_w = rec.get("power_w", rec.get("power"))
                hr_bpm = (
                    rec.get("hr_bpm")
                    or rec.get("heart_rate_bpm")
                    or rec.get("heart_rate")
                )
                speed_mps = rec.get("speed_mps", rec.get("speed"))
            else:
                lat = getattr(rec, "lat", None) or getattr(rec, "latitude", None)
                lon = getattr(rec, "lon", None) or getattr(rec, "longitude", None)
                ts = getattr(rec, "timestamp", None)
                elevation_m = getattr(rec, "elevation_m", None)
                power_w = getattr(rec, "power_w", None)
                hr_bpm = getattr(rec, "heart_rate_bpm", None) or getattr(
                    rec, "hr_bpm", None
                )
                speed_mps = getattr(rec, "speed_mps", None)

            if lat is None or lon is None or ts is None:
                continue

            points.append(
                {
                    "timestamp": ts,
                    "lat": lat,
                    "lon": lon,
                    "elevation_m": elevation_m,
                    "power_w": power_w,
                    "hr_bpm": hr_bpm,
                    "speed_mps": speed_mps,
                }
            )

        points.sort(key=lambda p: p["timestamp"])
        return points

    def build_canon_traversal_evidence(
        self,
        *,
        ride_id: UUID,
        ride_hash_hex: str,
        ride_parser_version: int,
        parsed_ride: ParsedRide,
    ) -> CanonTraversalEvidence:
        return CanonTraversalEvidence.build(
            ride_id=ride_id,
            ride_hash_hex=ride_hash_hex,
            ride_parser_version=ride_parser_version,
            parsed_ride=parsed_ride,
            tile_service=self.tile_service,
        )

    async def store_canon_traversal_evidence(self, evidence: CanonTraversalEvidence) -> None:
        await self.ride_repo.store_canon_traversal_evidence(evidence.to_row())

    async def load_canon_traversal_evidence(
        self,
        *,
        ride_id: UUID,
        ride_hash_hex: str,
        ride_parser_version: int,
    ) -> Optional[CanonTraversalEvidence]:
        row = await self.ride_repo.get_canon_traversal_evidence(
            ride_id=ride_id,
            ride_hash_hex=ride_hash_hex,
            ride_parser_version=ride_parser_version,
            evidence_version=CANON_TRAVERSAL_EVIDENCE_VERSION,
        )
        return CanonTraversalEvidence.from_row(row) if row else None

    async def update_ride_complete(
        self,
        *,
        ride_id: UUID,
        status: str,
        metrics: RideMetrics,
        parsed_ride: ParsedRide,
        dung_minted: int,
        tx_signature: Optional[str],
        cal_earned: int = 0,
        ride_hash_hex: Optional[str] = None,
        attestation_commitment_hex: Optional[str] = None,
        ride_parser_version: Optional[int] = None,
        preliminary_ride_hash_hex: Optional[str] = None,
        preliminary_parser_version: Optional[int] = None,
        canonical_match: Optional[bool] = None,
        review_reason: Optional[str] = None,
        ride_attestation_pda: Optional[str] = None,
        ride_attestation_tx_signature: Optional[str] = None,
        ride_attested_at: Optional[str] = None,
        effort_policy: Optional[RideEffortPolicy] = None,
        economic_tss: Optional[float] = None,
        reward_ftp_snapshot: Optional[RewardFtpSnapshot] = None,
        total_tss_after: Optional[float] = None,
        level_delta: Optional[int] = None,
        level_after: Optional[int] = None,
    ) -> None:
        effort_policy_fields = effort_policy.as_ride_fields() if effort_policy else {}
        reward_ftp_fields = (
            {
                "reward_ftp_w": reward_ftp_snapshot.ftp_w,
                "reward_ftp_source": reward_ftp_snapshot.source,
                "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
                "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
            }
            if reward_ftp_snapshot
            else {}
        )
        economic_tss_fields = (
            {"economic_tss": economic_tss}
            if economic_tss is not None
            else {}
        )
        await self.ride_repo.update_ride_status(
            ride_id=ride_id,
            status=status,
            started_at=(
                parsed_ride.started_at.isoformat() if parsed_ride.started_at else None
            ),
            completed_at=(
                parsed_ride.completed_at.isoformat()
                if parsed_ride.completed_at
                else None
            ),
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
            avg_hr_bpm=metrics.avg_hr_bpm,
            max_hr_bpm=metrics.max_hr_bpm,
            avg_speed_mps=metrics.avg_speed_mps,
            avg_cadence_rpm=metrics.avg_cadence_rpm,
            device_name=getattr(parsed_ride, "device_name", None),
            file_name=getattr(parsed_ride, "file_name", None),
            dung_minted=dung_minted,
            tx_signature=tx_signature,
            cal_earned=cal_earned,
            ride_hash_hex=ride_hash_hex,
            attestation_commitment_hex=attestation_commitment_hex,
            ride_parser_version=ride_parser_version,
            preliminary_ride_hash_hex=preliminary_ride_hash_hex,
            preliminary_parser_version=preliminary_parser_version,
            canonical_match=canonical_match,
            review_reason=review_reason,
            ride_attestation_pda=ride_attestation_pda,
            ride_attestation_tx_signature=ride_attestation_tx_signature,
            ride_attested_at=ride_attested_at,
            **effort_policy_fields,
            **economic_tss_fields,
            **reward_ftp_fields,
            total_tss_after=total_tss_after,
            level_delta=level_delta,
            level_after=level_after,
        )

    async def process_tile_projection(
        self,
        *,
        ride_id: UUID,
        user_id: UUID,
        points: List[Dict[str, Any]],
        ride_start_time: Optional[datetime] = None,
    ) -> tuple[int, int, List[Dict[str, Any]]]:
        tile_samples = await self.tile_service.project_points_to_tile_runs(
            points=points,
            resolution=10,
            start_time=ride_start_time,
        )

        if not tile_samples:
            return 0, 0, []

        stored_count = await self.tile_repo.store_activity_tile_samples(
            ride_id=ride_id,
            tile_samples=tile_samples,
        )
        tiles_explored = await self.tile_repo.update_wallet_tile_history(
            user_id=user_id,
            tile_ids=[sample["tile_id"] for sample in tile_samples],
            visited_at=ride_start_time or points[0]["timestamp"],
        )
        return stored_count, tiles_explored, tile_samples

    async def capture_profile_snapshot(
        self,
        *,
        wallet: str,
        ride_id: UUID,
        user_weight_kg: float,
        user_ftp_w: Optional[int],
        reward_ftp_snapshot: Optional[RewardFtpSnapshot] = None,
    ) -> None:
        try:
            payload = {
                "wallet": wallet,
                "weight_kg": user_weight_kg,
                "ftp_watts": user_ftp_w,
                "reference_type": "ride",
                "reference_id": str(ride_id),
            }
            if reward_ftp_snapshot:
                payload.update(
                    {
                        "reward_ftp_w": reward_ftp_snapshot.ftp_w,
                        "reward_ftp_source": reward_ftp_snapshot.source,
                        "reward_ftp_authority_id": reward_ftp_snapshot.authority_id,
                        "reward_ftp_policy_version": reward_ftp_snapshot.policy_version,
                    }
                )
            self._client.table("user_profile_snapshots").insert(payload).execute()
            logger.debug(
                f"[Snapshot] Captured profile snapshot: wallet=[redacted]... "
                f"weight={user_weight_kg}kg threshold={user_ftp_w} ride={ride_id}"
            )
        except Exception as exc:
            logger.warning(
                f"[Snapshot] Failed to capture profile snapshot (non-fatal): {exc}"
            )

    async def store_pattern_results(self, results: PatternResults) -> None:
        """Store all detected patterns to the database."""
        await self.pattern_repo.clear_patterns_for_activity(results.activity_id)

        for climb in results.climb_patterns:
            await self.pattern_repo.store_climb_pattern(
                pattern_id=climb.id,
                activity_id=climb.activity_id,
                wallet=climb.wallet,
                vert_m=climb.vert_m,
                time_s=climb.time_s,
                start_offset_s=climb.start_offset_s,
                end_offset_s=climb.end_offset_s,
                arena_id=climb.arena_id,
                avg_power_w=climb.avg_power_w,
                w_per_kg=climb.w_per_kg,
                avg_hr=climb.avg_hr,
                road_name=climb.road_name,
                road_grade=climb.road_grade,
                road_coverage_pct=climb.road_coverage_pct,
                attribution_summary=climb.attribution_summary,
                tile_ids=climb.tile_ids,
                distance_m=climb.distance_m,
                avg_gradient_pct=climb.avg_gradient_pct,
                signature_hex=climb.signature_hex,
                signature_v2_hex=climb.signature_v2_hex,
                persistence_m=climb.persistence_m,
                significance_g=climb.significance_g,
                significance_percentile=climb.significance_percentile,
                significance_return_period=climb.significance_return_period,
                significance_confidence_tier=climb.significance_confidence_tier,
                significance_bootstrapped=climb.significance_bootstrapped,
                significance_cell_h3=getattr(climb, "significance_cell_h3", None),
                start_lat=getattr(climb, "start_lat", None),
                start_lon=getattr(climb, "start_lon", None),
                end_lat=getattr(climb, "end_lat", None),
                end_lon=getattr(climb, "end_lon", None),
                economic_eligible=climb.economic_eligible,
                abstention_reasons=climb.abstention_reasons,
                match_trace=climb.match_trace,
                detector_version=climb.detector_version,
            )

        if results.steady_pattern:
            steady = results.steady_pattern
            await self.pattern_repo.store_steady_pattern(
                pattern_id=steady.id,
                activity_id=steady.activity_id,
                wallet=steady.wallet,
                duration_s=steady.duration_s,
                start_offset_s=steady.start_offset_s,
                end_offset_s=steady.end_offset_s,
                avg_power_w=steady.avg_power_w,
                np_power_w=steady.np_power_w,
                avg_hr=steady.avg_hr,
                intensity_index=steady.intensity_index,
                variability_index=steady.variability_index,
            )

        if results.exploration_pattern:
            exp = results.exploration_pattern
            await self.pattern_repo.store_exploration_pattern(
                pattern_id=exp.id,
                activity_id=exp.activity_id,
                wallet=exp.wallet,
                new_tiles_wallet=exp.new_tiles_wallet,
                total_tiles=exp.total_tiles,
                start_offset_s=exp.start_offset_s,
                end_offset_s=exp.end_offset_s,
                new_tiles_global=exp.new_tiles_global,
                night_minutes=exp.night_minutes,
            )

    async def build_sensor_lookup(
        self,
        ride_id: UUID,
    ) -> Optional[Callable[[datetime], Dict[str, float]]]:
        streams: Dict[str, tuple] = {}

        for stype in ["power", "heart_rate", "speed"]:
            try:
                stream = await self.ride_repo.get_activity_stream(ride_id, stype)
                if stream and stream.get("timestamps") and stream.get("values"):
                    ts_list = []
                    for ts_str in stream["timestamps"]:
                        try:
                            ts_list.append(
                                datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                            )
                        except (ValueError, TypeError):
                            ts_list.append(None)
                    vals = stream["values"]
                    paired = [(t, v) for t, v in zip(ts_list, vals) if t is not None]
                    if paired:
                        paired.sort(key=lambda x: x[0])
                        streams[stype] = (
                            [p[0] for p in paired],
                            [p[1] for p in paired],
                        )
            except Exception as exc:
                logger.debug(f"[Phase2] Could not load {stype} stream: {exc}")

        if not streams:
            return None

        logger.info(
            "[Phase2] Loaded sensor streams: "
            + ", ".join(f"{k}={len(v[0])}" for k, v in streams.items())
        )

        def lookup(ts: datetime) -> Dict[str, float]:
            result = {}
            for stype, (timestamps, values) in streams.items():
                idx = bisect.bisect_left(timestamps, ts)
                best_idx = None
                best_delta = None
                for candidate in (idx - 1, idx):
                    if 0 <= candidate < len(timestamps):
                        delta = abs((timestamps[candidate] - ts).total_seconds())
                        if best_delta is None or delta < best_delta:
                            best_delta = delta
                            best_idx = candidate
                if best_idx is not None and best_delta <= 2.0:
                    result[stype] = values[best_idx]
            return result

        return lookup

    async def get_pattern_results_from_db(
        self,
        ride_id: UUID,
    ) -> Optional[PatternResults]:
        """Reconstruct simplified PatternResults for Phase 3 achievements."""
        try:
            stored = await self.pattern_repo.get_patterns_for_activity(ride_id)

            ride_data = await self.ride_repo.get_ride(str(ride_id))
            user_id = ride_data.get("user_id") if ride_data else None
            user_wallet = ""
            if user_id:
                user_wallet = await self.user_repo.get_user_wallet(UUID(user_id)) or ""

            climb_patterns = [
                pattern_from_row(ClimbPattern, row)
                for row in stored.get("climb_patterns", [])
            ]
            steady_row = stored.get("steady_pattern")
            exploration_row = stored.get("exploration_pattern")
            return PatternResults(
                activity_id=ride_id,
                wallet=user_wallet,
                climb_patterns=climb_patterns,
                steady_pattern=(
                    pattern_from_row(SteadyPattern, steady_row)
                    if steady_row
                    else None
                ),
                exploration_pattern=(
                    pattern_from_row(ExplorationPattern, exploration_row)
                    if exploration_row
                    else None
                ),
            )
        except Exception as exc:
            logger.warning(f"[Phase3] Failed to get patterns from DB: {exc}")
            return None
