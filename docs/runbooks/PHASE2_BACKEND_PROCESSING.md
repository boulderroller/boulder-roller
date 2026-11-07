# Phase 2: Backend Processing Pipeline Runbook

## Worker Assignment
**Focus:** Ride processor orchestration, segment matching, achievements, Solana proofs
**FLAGS:** 3, 4, 5, 6

**Prerequisites:** FLAG 1, 2, 9 must be complete (tables exist, Celery configured)

---

## Overview

Build the complete ride processing pipeline that transforms raw ride files into fully analyzed activities with segment efforts, achievements, and Solana proofs.

---

## FLAG 3: Ride Processor Orchestration

### 3.1 Create Ride Processor Service

**File:** `backend/app/services/ride_processor.py`

```python
"""
Ride Processor: Orchestrates the complete ride processing pipeline.

Pipeline steps:
1. Parse file → extract raw records
2. Calculate metrics → TSS, NP, calories, etc.
3. Extract & store activity streams
4. Store GPS track points
5. Match segments → create efforts
6. Detect achievements
7. Create Solana proof
8. Mint DUNG tokens
9. Update ride record
"""

from uuid import UUID
from typing import Dict, Any, List, Optional
from dataclasses import dataclass
from datetime import datetime

from .ride_parser import parse_ride_file, ParsedRide
from .ride_metrics import RideMetrics, calculate_metrics
from .segment_matcher import SegmentMatcher
from .achievement_detector import AchievementDetector
from .proof_builder import ProofBuilder
from ..repositories import DatabaseRepository
from ..solana_client import SolanaClient


@dataclass
class ProcessingResult:
    metrics: RideMetrics
    segments_matched: int
    achievements_earned: int
    dung_minted: int
    tx_signature: Optional[str]


class RideProcessor:
    """Orchestrates ride file processing pipeline."""

    def __init__(self):
        self.repo = DatabaseRepository()
        self.solana = SolanaClient()
        self.segment_matcher = SegmentMatcher()
        self.achievement_detector = AchievementDetector()
        self.proof_builder = ProofBuilder()

    async def process_ride(
        self,
        ride_id: UUID,
        file_data_b64: str,
        file_type: str,
        user_id: UUID,
        user_weight_kg: float = 75.0,
        user_ftp_w: int = 200,
    ) -> Dict[str, Any]:
        """
        Main processing orchestration.

        Args:
            ride_id: UUID of the ride record
            file_data_b64: Base64-encoded file content
            file_type: "fit", "gpx", or "tcx"
            user_id: User who uploaded the ride
            user_weight_kg: User's weight for calorie calculation
            user_ftp_w: User's FTP for TSS calculation

        Returns:
            Dict with metrics, segments, achievements, dung_reward
        """
        try:
            # Update status to processing
            await self.repo.update_ride_status(ride_id, "processing")

            # Step 1: Parse the ride file
            parsed_ride = parse_ride_file(file_data_b64, file_type)

            if not parsed_ride.records:
                raise ValueError("No valid records found in file")

            # Step 2: Calculate metrics
            metrics = calculate_metrics(
                records=parsed_ride.records,
                user_weight_kg=user_weight_kg,
                user_ftp_w=user_ftp_w,
            )

            # Step 3: Extract and store activity streams
            await self._store_activity_streams(ride_id, parsed_ride)

            # Step 4: Store GPS track points
            if parsed_ride.gps_track:
                await self._store_gps_points(ride_id, parsed_ride.gps_track)

            # Step 5: Match segments
            segment_efforts = []
            if parsed_ride.gps_track:
                segment_efforts = await self.segment_matcher.match_segments(
                    ride_id=ride_id,
                    user_id=user_id,
                    gps_track=parsed_ride.gps_track,
                    metrics=metrics,
                    repo=self.repo,
                )

            # Step 6: Detect achievements
            achievements = await self.achievement_detector.detect_achievements(
                user_id=user_id,
                ride_id=ride_id,
                metrics=metrics,
                segment_efforts=segment_efforts,
                repo=self.repo,
            )

            # Step 7: Deduct CAL
            cal_cost = 1.0
            await self.repo.deduct_cal(str(user_id), cal_cost)

            # Step 8: Create proof and mint DUNG
            user_wallet = await self.repo.get_user_wallet(user_id)
            proof_result = await self.proof_builder.create_ride_proof(
                ride_id=ride_id,
                user_id=user_id,
                user_wallet=user_wallet,
                metrics=metrics,
                segment_efforts=segment_efforts,
                solana=self.solana,
                repo=self.repo,
            )

            # Step 9: Update ride record with all data
            await self._update_ride_complete(
                ride_id=ride_id,
                metrics=metrics,
                parsed_ride=parsed_ride,
                dung_minted=proof_result["dung_amount"],
                tx_signature=proof_result.get("tx_signature"),
            )

            return {
                "status": "completed",
                "metrics": metrics.to_dict(),
                "segments": len(segment_efforts),
                "achievements": len(achievements),
                "dung_reward": proof_result["dung_amount"],
                "tx_signature": proof_result.get("tx_signature"),
            }

        except Exception as e:
            await self.repo.update_ride_status(
                ride_id, "failed", error_message=str(e)
            )
            raise

    async def _store_activity_streams(
        self,
        ride_id: UUID,
        parsed_ride: ParsedRide
    ) -> None:
        """Extract and store time-series streams from parsed records."""
        streams = {
            "power": [],
            "heart_rate": [],
            "cadence": [],
            "speed": [],
        }
        timestamps = {k: [] for k in streams.keys()}

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

        # Store each non-empty stream
        for stream_type, values in streams.items():
            if values:
                await self.repo.store_activity_stream(
                    ride_id=ride_id,
                    stream_type=stream_type,
                    timestamps=timestamps[stream_type],
                    values=values,
                )

    async def _store_gps_points(
        self,
        ride_id: UUID,
        gps_track: List[Dict]
    ) -> None:
        """Store GPS track points for segment matching."""
        points = [
            {
                "timestamp": p["timestamp"],
                "latitude": p["latitude"],
                "longitude": p["longitude"],
                "elevation": p.get("elevation_m"),
                "distance": p.get("distance_m"),
            }
            for p in gps_track
        ]
        await self.repo.store_gps_points(ride_id, points)

    async def _update_ride_complete(
        self,
        ride_id: UUID,
        metrics: RideMetrics,
        parsed_ride: ParsedRide,
        dung_minted: int,
        tx_signature: Optional[str],
    ) -> None:
        """Update ride record with all computed data."""
        await self.repo.update_ride_status(
            ride_id=ride_id,
            status="completed",
            # Timing
            started_at=parsed_ride.started_at.isoformat() if parsed_ride.started_at else None,
            completed_at=parsed_ride.ended_at.isoformat() if parsed_ride.ended_at else None,
            duration_sec=metrics.duration_sec,
            # Metrics
            tss=metrics.tss,
            kcals=metrics.kcals,
            distance_m=metrics.distance_m,
            elevation_gain_m=metrics.elevation_gain_m,
            # Power
            avg_power_w=metrics.avg_power_w,
            max_power_w=metrics.max_power_w,
            normalized_power_w=metrics.normalized_power_w,
            # HR
            avg_hr_bpm=metrics.avg_hr_bpm,
            max_hr_bpm=metrics.max_hr_bpm,
            # Speed/Cadence
            avg_speed_mps=metrics.avg_speed_mps,
            avg_cadence_rpm=metrics.avg_cadence_rpm,
            # Device
            device_name=parsed_ride.device_name,
            file_name=parsed_ride.file_name,
            # Rewards
            dung_minted=dung_minted,
            tx_signature=tx_signature,
        )
```

---

## FLAG 4: Segment Matching

### 4.1 Create Segment Matcher Service

**File:** `backend/app/services/segment_matcher.py`

```python
"""
Segment Matcher: Matches ride GPS tracks against segment definitions.

Algorithm:
1. Get bounding box of ride
2. Query segments whose start/end points fall within bbox
3. For each candidate segment:
   - Find where ride passes near segment start
   - Find where ride passes near segment end
   - If both found, extract subsection
   - Calculate effort metrics for subsection
   - Compare against segment leaderboard
4. Return matched segment efforts
"""

from uuid import UUID
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime
import math

from .ride_metrics import RideMetrics


@dataclass
class SegmentEffort:
    segment_id: int
    segment_name: str
    elapsed_time_sec: int
    effort_score: float
    average_power_w: Optional[float]
    average_hr_bpm: Optional[float]
    elevation_gain_m: Optional[float]
    distance_m: Optional[float]
    rank: Optional[int]
    is_pr: bool
    is_kom: bool


class SegmentMatcher:
    """Matches ride GPS tracks to segment definitions."""

    # Maximum distance from segment start/end to consider a match (meters)
    MATCH_THRESHOLD_M = 50

    async def match_segments(
        self,
        ride_id: UUID,
        user_id: UUID,
        gps_track: List[Dict],
        metrics: RideMetrics,
        repo,
    ) -> List[SegmentEffort]:
        """
        Match ride GPS track against all segments.

        Args:
            ride_id: UUID of the ride
            user_id: UUID of the user
            gps_track: List of GPS points [{lat, lon, timestamp, ...}]
            metrics: Calculated ride metrics
            repo: Database repository

        Returns:
            List of matched SegmentEffort objects
        """
        if len(gps_track) < 2:
            return []

        # Step 1: Calculate ride bounding box
        bbox = self._calculate_bbox(gps_track)

        # Step 2: Query nearby segments
        nearby_segments = await repo.list_segments(
            min_lat=bbox["min_lat"],
            max_lat=bbox["max_lat"],
            min_lon=bbox["min_lon"],
            max_lon=bbox["max_lon"],
        )

        efforts = []
        for segment in nearby_segments:
            effort = await self._match_single_segment(
                ride_id=ride_id,
                user_id=user_id,
                gps_track=gps_track,
                segment=segment,
                repo=repo,
            )
            if effort:
                efforts.append(effort)
                # Store effort in database
                await self._store_effort(ride_id, user_id, effort, repo)

        return efforts

    def _calculate_bbox(self, gps_track: List[Dict]) -> Dict:
        """Calculate bounding box with padding."""
        lats = [p["latitude"] for p in gps_track]
        lons = [p["longitude"] for p in gps_track]

        # Add ~500m padding
        padding = 0.005  # ~500m at mid-latitudes

        return {
            "min_lat": min(lats) - padding,
            "max_lat": max(lats) + padding,
            "min_lon": min(lons) - padding,
            "max_lon": max(lons) + padding,
        }

    async def _match_single_segment(
        self,
        ride_id: UUID,
        user_id: UUID,
        gps_track: List[Dict],
        segment: Dict,
        repo,
    ) -> Optional[SegmentEffort]:
        """
        Attempt to match a single segment against the ride.

        Returns SegmentEffort if matched, None otherwise.
        """
        start_point = (segment["start_lat"], segment["start_lon"])
        end_point = (segment["end_lat"], segment["end_lon"])

        # Find closest points to segment start/end
        start_idx = self._find_closest_point_index(gps_track, start_point)
        if start_idx is None:
            return None

        # Search for end point only after start point
        end_idx = self._find_closest_point_index(
            gps_track[start_idx:], end_point
        )
        if end_idx is None:
            return None

        end_idx = start_idx + end_idx  # Adjust to absolute index

        # Verify we're actually close enough
        if (self._distance_to_point(gps_track[start_idx], start_point) > self.MATCH_THRESHOLD_M or
            self._distance_to_point(gps_track[end_idx], end_point) > self.MATCH_THRESHOLD_M):
            return None

        # Extract subsection
        subsection = gps_track[start_idx:end_idx + 1]
        if len(subsection) < 2:
            return None

        # Calculate effort metrics
        start_time = subsection[0]["timestamp"]
        end_time = subsection[-1]["timestamp"]
        elapsed_sec = int((end_time - start_time).total_seconds())

        # Simple effort score: inverse of time (lower time = higher score)
        # Could be enhanced with power weighting
        effort_score = 3600.0 / max(elapsed_sec, 1)  # Normalize to "per hour"

        # Calculate elevation gain in subsection
        elevation_gain = self._calculate_elevation_gain(subsection)

        # Calculate distance
        distance = self._calculate_track_distance(subsection)

        # Check for PR/KOM
        best_effort = await repo.get_user_best_segment_effort(
            user_id, segment["id"]
        )
        segment_best = await repo.get_segment_best_effort(segment["id"])

        is_pr = best_effort is None or elapsed_sec < best_effort["elapsed_time_sec"]
        is_kom = segment_best is None or elapsed_sec < segment_best["elapsed_time_sec"]

        # Calculate rank
        rank = await repo.get_segment_effort_rank(segment["id"], elapsed_sec)

        return SegmentEffort(
            segment_id=segment["id"],
            segment_name=segment["name"],
            elapsed_time_sec=elapsed_sec,
            effort_score=effort_score,
            average_power_w=None,  # Would need power data from subsection
            average_hr_bpm=None,
            elevation_gain_m=elevation_gain,
            distance_m=distance,
            rank=rank,
            is_pr=is_pr,
            is_kom=is_kom,
        )

    def _find_closest_point_index(
        self,
        track: List[Dict],
        target: tuple
    ) -> Optional[int]:
        """Find index of closest point to target within threshold."""
        min_dist = float("inf")
        min_idx = None

        for i, point in enumerate(track):
            dist = self._haversine_distance(
                point["latitude"], point["longitude"],
                target[0], target[1]
            )
            if dist < min_dist and dist < self.MATCH_THRESHOLD_M:
                min_dist = dist
                min_idx = i

        return min_idx

    def _distance_to_point(self, point: Dict, target: tuple) -> float:
        """Calculate distance from point to target in meters."""
        return self._haversine_distance(
            point["latitude"], point["longitude"],
            target[0], target[1]
        )

    def _haversine_distance(
        self,
        lat1: float, lon1: float,
        lat2: float, lon2: float
    ) -> float:
        """Calculate distance between two points in meters."""
        R = 6371000  # Earth radius in meters

        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lon2 - lon1)

        a = (math.sin(delta_phi / 2) ** 2 +
             math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
        c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

        return R * c

    def _calculate_elevation_gain(self, track: List[Dict]) -> float:
        """Calculate total elevation gain in track."""
        gain = 0.0
        for i in range(1, len(track)):
            prev_ele = track[i - 1].get("elevation_m")
            curr_ele = track[i].get("elevation_m")
            if prev_ele is not None and curr_ele is not None:
                diff = curr_ele - prev_ele
                if diff > 0:
                    gain += diff
        return gain

    def _calculate_track_distance(self, track: List[Dict]) -> float:
        """Calculate total distance of track in meters."""
        total = 0.0
        for i in range(1, len(track)):
            total += self._haversine_distance(
                track[i - 1]["latitude"], track[i - 1]["longitude"],
                track[i]["latitude"], track[i]["longitude"],
            )
        return total

    async def _store_effort(
        self,
        ride_id: UUID,
        user_id: UUID,
        effort: SegmentEffort,
        repo,
    ) -> None:
        """Store segment effort in database."""
        await repo.create_segment_effort(
            ride_id=ride_id,
            user_id=user_id,
            segment_id=effort.segment_id,
            elapsed_time_sec=effort.elapsed_time_sec,
            effort_score=effort.effort_score,
            average_power_w=effort.average_power_w,
            average_hr_bpm=effort.average_hr_bpm,
            elevation_gain_m=effort.elevation_gain_m,
            distance_m=effort.distance_m,
            is_pr=effort.is_pr,
            is_kom=effort.is_kom,
            rank_at_time=effort.rank,
        )
```

---

## FLAG 5: Achievement Detection

### 5.1 Create Achievement Detector Service

**File:** `backend/app/services/achievement_detector.py`

```python
"""
Achievement Detector: Identifies and awards achievements based on ride performance.

Achievement Types:
- KOM: King of Mountain (fastest segment time)
- PR: Personal Record (beat your own segment time)
- power_record: New all-time max power
- distance_milestone: Total distance milestones (100km, 1000km, etc)
- elevation_milestone: Total climbing milestones
- streak: Consecutive riding days
- first_ride: First ride uploaded
- badge: Special achievements (e.g., climber, sprinter)
"""

from uuid import UUID
from typing import List, Dict, Optional
from dataclasses import dataclass
from datetime import datetime, timedelta

from .ride_metrics import RideMetrics
from .segment_matcher import SegmentEffort


@dataclass
class Achievement:
    achievement_type: str
    title: str
    description: str
    value: Optional[float]
    rank: Optional[int]
    segment_id: Optional[int]
    metadata: Dict


class AchievementDetector:
    """Detects and awards achievements based on ride data."""

    # Distance milestones in km
    DISTANCE_MILESTONES = [100, 500, 1000, 2500, 5000, 10000]

    # Elevation milestones in meters
    ELEVATION_MILESTONES = [1000, 5000, 10000, 25000, 50000, 100000]

    async def detect_achievements(
        self,
        user_id: UUID,
        ride_id: UUID,
        metrics: RideMetrics,
        segment_efforts: List[SegmentEffort],
        repo,
    ) -> List[Achievement]:
        """
        Detect all achievements from a ride.

        Args:
            user_id: UUID of the user
            ride_id: UUID of the ride
            metrics: Calculated ride metrics
            segment_efforts: Matched segment efforts
            repo: Database repository

        Returns:
            List of earned Achievement objects
        """
        achievements = []

        # Check segment achievements (KOM, PR)
        for effort in segment_efforts:
            if effort.is_kom:
                achievements.append(self._create_kom_achievement(effort))
            elif effort.is_pr:
                achievements.append(self._create_pr_achievement(effort))
            elif effort.rank and effort.rank <= 3:
                achievements.append(self._create_podium_achievement(effort))

        # Check power record
        power_achievement = await self._check_power_record(
            user_id, metrics, repo
        )
        if power_achievement:
            achievements.append(power_achievement)

        # Check distance milestones
        distance_achievement = await self._check_distance_milestone(
            user_id, metrics, repo
        )
        if distance_achievement:
            achievements.append(distance_achievement)

        # Check elevation milestones
        elevation_achievement = await self._check_elevation_milestone(
            user_id, metrics, repo
        )
        if elevation_achievement:
            achievements.append(elevation_achievement)

        # Check for first ride
        is_first = await self._is_first_ride(user_id, repo)
        if is_first:
            achievements.append(Achievement(
                achievement_type="first_ride",
                title="First Ride!",
                description="Welcome to Boulder Rollers! You've completed your first ride.",
                value=None,
                rank=None,
                segment_id=None,
                metadata={},
            ))

        # Check riding streak
        streak_achievement = await self._check_streak(user_id, repo)
        if streak_achievement:
            achievements.append(streak_achievement)

        # Store all achievements
        for achievement in achievements:
            await self._store_achievement(
                user_id, ride_id, achievement, repo
            )

        return achievements

    def _create_kom_achievement(self, effort: SegmentEffort) -> Achievement:
        return Achievement(
            achievement_type="kom",
            title=f"KOM: {effort.segment_name}",
            description=f"You're the fastest on {effort.segment_name}!",
            value=float(effort.elapsed_time_sec),
            rank=1,
            segment_id=effort.segment_id,
            metadata={"elapsed_sec": effort.elapsed_time_sec},
        )

    def _create_pr_achievement(self, effort: SegmentEffort) -> Achievement:
        return Achievement(
            achievement_type="pr",
            title=f"PR: {effort.segment_name}",
            description=f"New personal record on {effort.segment_name}!",
            value=float(effort.elapsed_time_sec),
            rank=effort.rank,
            segment_id=effort.segment_id,
            metadata={"elapsed_sec": effort.elapsed_time_sec},
        )

    def _create_podium_achievement(self, effort: SegmentEffort) -> Achievement:
        return Achievement(
            achievement_type="podium",
            title=f"Top {effort.rank}: {effort.segment_name}",
            description=f"You're #{effort.rank} on {effort.segment_name}!",
            value=float(effort.elapsed_time_sec),
            rank=effort.rank,
            segment_id=effort.segment_id,
            metadata={"elapsed_sec": effort.elapsed_time_sec},
        )

    async def _check_power_record(
        self,
        user_id: UUID,
        metrics: RideMetrics,
        repo,
    ) -> Optional[Achievement]:
        """Check if this ride set a new power record."""
        if not metrics.max_power_w:
            return None

        prev_max = await repo.get_user_max_power(user_id)
        if prev_max and metrics.max_power_w <= prev_max:
            return None

        return Achievement(
            achievement_type="power_record",
            title="New Power Record!",
            description=f"You hit {metrics.max_power_w}W - your highest ever!",
            value=float(metrics.max_power_w),
            rank=None,
            segment_id=None,
            metadata={"previous_max": prev_max},
        )

    async def _check_distance_milestone(
        self,
        user_id: UUID,
        metrics: RideMetrics,
        repo,
    ) -> Optional[Achievement]:
        """Check if user crossed a distance milestone."""
        prev_total = await repo.get_user_total_distance(user_id)
        new_total = prev_total + (metrics.distance_m or 0) / 1000  # km

        for milestone in self.DISTANCE_MILESTONES:
            if prev_total < milestone <= new_total:
                return Achievement(
                    achievement_type="distance_milestone",
                    title=f"{milestone}km Club!",
                    description=f"You've ridden a total of {milestone}km!",
                    value=float(milestone),
                    rank=None,
                    segment_id=None,
                    metadata={"total_km": new_total},
                )
        return None

    async def _check_elevation_milestone(
        self,
        user_id: UUID,
        metrics: RideMetrics,
        repo,
    ) -> Optional[Achievement]:
        """Check if user crossed an elevation milestone."""
        prev_total = await repo.get_user_total_elevation(user_id)
        new_total = prev_total + (metrics.elevation_gain_m or 0)

        for milestone in self.ELEVATION_MILESTONES:
            if prev_total < milestone <= new_total:
                return Achievement(
                    achievement_type="elevation_milestone",
                    title=f"{milestone}m Climber!",
                    description=f"You've climbed a total of {milestone}m!",
                    value=float(milestone),
                    rank=None,
                    segment_id=None,
                    metadata={"total_m": new_total},
                )
        return None

    async def _is_first_ride(self, user_id: UUID, repo) -> bool:
        """Check if this is the user's first ride."""
        count = await repo.get_user_ride_count(user_id)
        return count == 1  # This ride is the first

    async def _check_streak(
        self,
        user_id: UUID,
        repo,
    ) -> Optional[Achievement]:
        """Check for consecutive day riding streak."""
        streak = await repo.get_user_riding_streak(user_id)

        milestones = [7, 14, 30, 60, 100, 365]
        for days in milestones:
            if streak == days:
                return Achievement(
                    achievement_type="streak",
                    title=f"{days}-Day Streak!",
                    description=f"You've ridden {days} days in a row!",
                    value=float(days),
                    rank=None,
                    segment_id=None,
                    metadata={"streak_days": streak},
                )
        return None

    async def _store_achievement(
        self,
        user_id: UUID,
        ride_id: UUID,
        achievement: Achievement,
        repo,
    ) -> None:
        """Store achievement in database."""
        await repo.create_achievement(
            user_id=user_id,
            ride_id=ride_id,
            achievement_type=achievement.achievement_type,
            title=achievement.title,
            description=achievement.description,
            value=achievement.value,
            rank=achievement.rank,
            segment_id=achievement.segment_id,
            metadata=achievement.metadata,
        )
```

---

## FLAG 6: Enhanced Solana Proofs

### 6.1 Create Proof Builder Service

**File:** `backend/app/services/proof_builder.py`

```python
"""
Proof Builder: Creates verifiable proofs for ride efforts on Solana.

Proof contains:
- Ride ID
- User wallet
- Effort score (TSS-based)
- Timestamp
- Segment efforts (for KOM verification)
- Hash of ride data

DUNG reward = floor(TSS)
"""

from uuid import UUID, uuid4
from typing import Dict, List, Optional
from datetime import datetime
import hashlib
import json

from .ride_metrics import RideMetrics
from .segment_matcher import SegmentEffort


class ProofBuilder:
    """Creates cryptographic proofs and mints DUNG tokens."""

    async def create_ride_proof(
        self,
        ride_id: UUID,
        user_id: UUID,
        user_wallet: str,
        metrics: RideMetrics,
        segment_efforts: List[SegmentEffort],
        solana,
        repo,
    ) -> Dict:
        """
        Create a verifiable proof and mint DUNG tokens.

        Args:
            ride_id: UUID of the ride
            user_id: UUID of the user
            user_wallet: User's Solana wallet address
            metrics: Calculated ride metrics
            segment_efforts: Matched segment efforts
            solana: Solana client
            repo: Database repository

        Returns:
            Dict with proof_id, dung_amount, tx_signature
        """
        # Calculate DUNG reward based on TSS
        dung_amount = self._calculate_dung_reward(metrics)

        # Build proof data structure
        proof_data = self._build_proof_data(
            ride_id=ride_id,
            user_id=user_id,
            user_wallet=user_wallet,
            metrics=metrics,
            segment_efforts=segment_efforts,
            dung_amount=dung_amount,
        )

        # Create proof record in database
        proof_id = str(uuid4())
        await repo.create_proof(
            proof_id=proof_id,
            ride_id=str(ride_id),
            user_id=str(user_id),
            effort_score=metrics.tss or 0,
            dung_amount=dung_amount,
            proof_hash=proof_data["hash"],
            status="pending",
        )

        # Mint DUNG tokens on Solana
        tx_result = await solana.mint_dung(
            user_pubkey=user_wallet,
            amount=dung_amount,
            proof_id=proof_id,
            tss=int(metrics.tss or 0),
        )

        # Update proof with transaction result
        tx_signature = tx_result.get("signature")
        status = "confirmed" if tx_signature else "failed"

        await repo.update_proof_status(
            proof_id=proof_id,
            status=status,
            tx_signature=tx_signature,
        )

        # Record mint event
        await repo.record_mint_event(
            user_id=str(user_id),
            ride_id=str(ride_id),
            proof_id=proof_id,
            dung_amount=dung_amount,
            tx_signature=tx_signature,
            status=status,
        )

        return {
            "proof_id": proof_id,
            "dung_amount": dung_amount,
            "tx_signature": tx_signature,
            "status": status,
        }

    def _calculate_dung_reward(self, metrics: RideMetrics) -> int:
        """
        Calculate DUNG reward from ride metrics.

        Formula: DUNG = floor(TSS)
        Minimum: 1 DUNG per valid ride
        Maximum: 500 DUNG per ride (prevent gaming)
        """
        tss = metrics.tss or 0

        # Minimum reward for any valid ride
        if tss < 1:
            return 1

        # Cap maximum reward
        return min(int(tss), 500)

    def _build_proof_data(
        self,
        ride_id: UUID,
        user_id: UUID,
        user_wallet: str,
        metrics: RideMetrics,
        segment_efforts: List[SegmentEffort],
        dung_amount: int,
    ) -> Dict:
        """Build proof data structure with hash."""
        proof_data = {
            "version": "1.0",
            "ride_id": str(ride_id),
            "user_id": str(user_id),
            "user_wallet": user_wallet,
            "timestamp": datetime.utcnow().isoformat(),
            "metrics": {
                "tss": metrics.tss,
                "duration_sec": metrics.duration_sec,
                "distance_m": metrics.distance_m,
                "elevation_m": metrics.elevation_gain_m,
                "avg_power_w": metrics.avg_power_w,
            },
            "segments": [
                {
                    "segment_id": e.segment_id,
                    "elapsed_sec": e.elapsed_time_sec,
                    "is_kom": e.is_kom,
                    "is_pr": e.is_pr,
                }
                for e in segment_efforts
            ],
            "reward": {
                "dung_amount": dung_amount,
            },
        }

        # Create hash for verification
        proof_json = json.dumps(proof_data, sort_keys=True)
        proof_hash = hashlib.sha256(proof_json.encode()).hexdigest()

        proof_data["hash"] = proof_hash

        return proof_data
```

---

## Testing Checklist

- [ ] RideProcessor orchestrates full pipeline
- [ ] Activity streams extracted and stored correctly
- [ ] GPS points stored with correct sequence
- [ ] Segment matching identifies valid segments
- [ ] KOM/PR detection works correctly
- [ ] Achievement detection triggers appropriately
- [ ] DUNG calculation matches TSS
- [ ] Solana mint transaction succeeds
- [ ] Proof data hash is consistent
- [ ] Failed rides marked correctly with error

---

## Repository Methods Needed

Add these to `repositories.py`:
```python
# Segments
async def list_segments(self, min_lat, max_lat, min_lon, max_lon) -> List[Dict]
async def get_segment_best_effort(self, segment_id: int) -> Optional[Dict]
async def get_user_best_segment_effort(self, user_id, segment_id) -> Optional[Dict]
async def get_segment_effort_rank(self, segment_id, elapsed_sec) -> int
async def create_segment_effort(self, **kwargs) -> UUID

# Achievements
async def create_achievement(self, **kwargs) -> UUID
async def get_user_max_power(self, user_id) -> Optional[float]
async def get_user_total_distance(self, user_id) -> float
async def get_user_total_elevation(self, user_id) -> float
async def get_user_ride_count(self, user_id) -> int
async def get_user_riding_streak(self, user_id) -> int

# Proofs
async def create_proof(self, **kwargs) -> None
async def update_proof_status(self, proof_id, status, tx_signature) -> None
```
