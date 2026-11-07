"""
Replay Service: Reprocess rides through the pipeline and compare results.

Implements A5 Deliverables 3 (Replay Model) and 4 (Structured Diffing).

Key operations:
  1. create_replay_batch — create a batch for mass reprocessing
  2. replay_ride — reprocess a single ride, store results in staging
  3. generate_scorecard — summarize batch results for human review
  4. generate_diff — structured comparison of old vs new outputs
  5. generate_explanation — plain-English narrative from a diff
  6. promote_batch — disabled until real promotion semantics exist

All replay operations write to STAGING tables (replay_ride_results), never
to production tables (rides, patterns_climb, wallet_points).
"""
from __future__ import annotations

import base64
import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

from ..repositories import (
    create_ride_repository,
    create_pattern_repository,
    create_user_repository,
    get_supabase_client,
)
from .reward_ftp import RewardFtpSnapshot
from .reward_threshold import parse_threshold_rider_projection

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Data structures
# ---------------------------------------------------------------------------

@dataclass
class ReplayBatch:
    """In-memory representation of a replay_batches row."""
    id: str
    scope: str
    status: str
    from_version_id: Optional[int]
    to_version_id: Optional[int]
    ride_ids: Optional[List[str]]
    total_rides: int
    completed_rides: int
    failed_rides: int
    dry_run: bool
    scorecard: Optional[Dict] = None
    created_at: Optional[str] = None


@dataclass
class RideDiff:
    """Structured diff between two processing runs."""
    ride_id: str
    metrics: Dict[str, Any] = field(default_factory=dict)
    climbs: Dict[str, Any] = field(default_factory=dict)
    vault_matches: Dict[str, Any] = field(default_factory=dict)
    economic: Dict[str, Any] = field(default_factory=dict)

    @property
    def has_metric_changes(self) -> bool:
        return any(
            v.get("delta", 0) != 0
            for v in self.metrics.values()
            if isinstance(v, dict)
        )

    @property
    def has_climb_changes(self) -> bool:
        count_info = self.climbs.get("count", {})
        return (
            count_info.get("delta", 0) != 0
            or bool(self.climbs.get("added"))
            or bool(self.climbs.get("removed"))
            or bool(self.climbs.get("modified"))
        )

    @property
    def has_match_changes(self) -> bool:
        count_info = self.vault_matches.get("count", {})
        return (
            count_info.get("delta", 0) != 0
            or bool(self.vault_matches.get("added"))
            or bool(self.vault_matches.get("removed"))
        )

    @property
    def has_economic_changes(self) -> bool:
        return any(
            v.get("delta", 0) != 0
            for v in self.economic.values()
            if isinstance(v, dict)
        )

    @property
    def has_any_changes(self) -> bool:
        return (
            self.has_metric_changes
            or self.has_climb_changes
            or self.has_match_changes
            or self.has_economic_changes
        )

    def to_dict(self) -> Dict:
        return {
            "ride_id": self.ride_id,
            "metrics": self.metrics,
            "climbs": self.climbs,
            "vault_matches": self.vault_matches,
            "economic": self.economic,
        }


# ---------------------------------------------------------------------------
# Service
# ---------------------------------------------------------------------------

class ReplayService:
    """
    Service for replaying rides through the processing pipeline.

    All replay results are written to staging tables. Production tables
    are never modified by replay operations.
    """

    def __init__(self, client=None):
        self._client = client or get_supabase_client()

    # -----------------------------------------------------------------------
    # 1. create_replay_batch
    # -----------------------------------------------------------------------

    async def create_replay_batch(
        self,
        scope: str,
        ride_ids: Optional[List[str]] = None,
        wallet: Optional[str] = None,
        epoch_id: Optional[int] = None,
        from_version_id: Optional[int] = None,
        to_version_id: Optional[int] = None,
        dry_run: bool = False,
    ) -> ReplayBatch:
        """
        Create a new replay batch.

        Args:
            scope: One of 'ride', 'user', 'epoch', 'mass'
            ride_ids: List of ride IDs to replay (for scope='ride' or 'mass')
            wallet: User wallet (for scope='user')
            epoch_id: Epoch number (for scope='epoch')
            from_version_id: Pipeline version that produced the originals
            to_version_id: Pipeline version to use for replay
            dry_run: If True, replay but do not allow promotion

        Returns:
            ReplayBatch with the created batch ID
        """
        if scope not in ("ride", "user", "epoch", "mass"):
            raise ValueError(f"Invalid scope: {scope}. Must be ride, user, epoch, or mass")

        # For user scope, fetch all ride IDs for the wallet
        effective_ride_ids = ride_ids
        if scope == "user" and wallet and not ride_ids:
            effective_ride_ids = await self._get_rides_for_wallet(wallet)

        total_rides = len(effective_ride_ids) if effective_ride_ids else 0

        payload = {
            "scope": scope,
            "status": "pending",
            "from_version_id": from_version_id,
            "to_version_id": to_version_id,
            "ride_ids": effective_ride_ids,
            "wallet": wallet,
            "epoch_id": epoch_id,
            "total_rides": total_rides,
            "completed_rides": 0,
            "failed_rides": 0,
            "dry_run": dry_run,
        }

        result = self._client.table("replay_batches").insert(payload).execute()
        row = result.data[0] if result.data else {}

        return ReplayBatch(
            id=row.get("id", ""),
            scope=scope,
            status="pending",
            from_version_id=from_version_id,
            to_version_id=to_version_id,
            ride_ids=effective_ride_ids,
            total_rides=total_rides,
            completed_rides=0,
            failed_rides=0,
            dry_run=dry_run,
            created_at=row.get("created_at"),
        )

    # -----------------------------------------------------------------------
    # 2. replay_ride
    # -----------------------------------------------------------------------

    async def replay_ride(self, batch_id: str, ride_id: str) -> Dict[str, Any]:
        """
        Reprocess a single ride and store results in staging.

        Steps:
        1. Fetch original ride record
        2. Download raw file from Supabase Storage
        3. Fetch user profile snapshot (weight/FTP at original processing time)
        4. Run the pipeline (parse, metrics, patterns)
        5. Fetch original outputs for comparison
        6. Generate structured diff
        7. Store results in replay_ride_results and ride_diffs

        Returns:
            Dict with replay results including diff and status
        """
        start_ms = time.monotonic()

        try:
            # Mark batch as running (idempotent)
            self._client.table("replay_batches").update({
                "status": "running",
                "started_at": datetime.now(timezone.utc).isoformat(),
            }).eq("id", batch_id).eq("status", "pending").execute()

            # 1. Fetch original ride record
            ride_repo = create_ride_repository()
            ride = await ride_repo.get_ride(ride_id)
            if not ride:
                raise ValueError(f"Ride {ride_id} not found")

            raw_file_path = ride.get("raw_file_path")
            if not raw_file_path:
                raise ValueError(
                    f"Ride {ride_id} has no raw_file_path — cannot replay "
                    "rides uploaded before file storage was enabled"
                )

            # 2. Download raw file from Supabase Storage
            from .file_storage import create_file_storage_service
            storage = create_file_storage_service()
            raw_bytes = await storage.download_ride_file(raw_file_path)
            file_type = ride.get("file_type", "fit")

            # 3. Fetch user profile snapshot from original processing time
            weight_kg, ftp_w = await self._get_profile_snapshot(
                ride_id=ride_id,
                user_id=ride.get("user_id"),
            )
            try:
                reward_ftp_w = RewardFtpSnapshot.from_row(ride).ftp_w
            except ValueError:
                reward_ftp_w = None

            # 4. Run the pipeline (reprocess the ride)
            replay_output = await self._run_pipeline(
                raw_bytes=raw_bytes,
                file_type=file_type,
                user_weight_kg=weight_kg,
                user_ftp_w=ftp_w,
                reward_ftp_w=reward_ftp_w,
            )

            # 5. Fetch original outputs for comparison
            original_output = await self._fetch_original_outputs(ride_id, ride)

            # 6. Generate structured diff
            diff = self.generate_diff(
                ride_id=ride_id,
                old_metrics=original_output.get("metrics", {}),
                new_metrics=replay_output.get("metrics", {}),
                old_climbs=original_output.get("climbs", []),
                new_climbs=replay_output.get("climbs", []),
                old_vault_matches=original_output.get("vault_matches", []),
                new_vault_matches=replay_output.get("vault_matches", []),
                old_economic=original_output.get("economic", {}),
                new_economic=replay_output.get("economic", {}),
            )

            explanation = self.generate_explanation(diff.to_dict())
            duration_ms = int((time.monotonic() - start_ms) * 1000)

            # 7. Store results in staging
            economic_delta = {}
            if diff.has_economic_changes:
                economic_delta = diff.economic

            result_payload = {
                "batch_id": batch_id,
                "ride_id": ride_id,
                "status": "completed",
                "metrics": replay_output.get("metrics"),
                "climbs": replay_output.get("climbs"),
                "vault_matches": replay_output.get("vault_matches"),
                "economic_delta": economic_delta if economic_delta else None,
                "processed_at": datetime.now(timezone.utc).isoformat(),
                "duration_ms": duration_ms,
            }

            self._client.table("replay_ride_results").upsert(
                result_payload,
                on_conflict="batch_id,ride_id",
            ).execute()

            # Store diff
            if diff.has_any_changes:
                # Get version IDs from the batch
                batch_row = self._client.table("replay_batches").select(
                    "from_version_id, to_version_id"
                ).eq("id", batch_id).limit(1).execute()
                batch_data = batch_row.data[0] if batch_row.data else {}

                diff_payload = {
                    "ride_id": ride_id,
                    "batch_id": batch_id,
                    "old_version_id": batch_data.get("from_version_id"),
                    "new_version_id": batch_data.get("to_version_id"),
                    "diff": diff.to_dict(),
                    "explanation": explanation,
                    "has_metric_changes": diff.has_metric_changes,
                    "has_climb_changes": diff.has_climb_changes,
                    "has_match_changes": diff.has_match_changes,
                    "has_economic_changes": diff.has_economic_changes,
                }
                self._client.table("ride_diffs").insert(diff_payload).execute()

            # Update batch progress
            self._client.rpc("increment_replay_progress", {
                "p_batch_id": batch_id,
                "p_is_success": True,
            }).execute()

            logger.info(
                f"[Replay] Completed ride {ride_id} in {duration_ms}ms "
                f"(changes: {'yes' if diff.has_any_changes else 'none'})"
            )

            return {
                "ride_id": ride_id,
                "status": "completed",
                "duration_ms": duration_ms,
                "has_changes": diff.has_any_changes,
                "diff": diff.to_dict(),
                "explanation": explanation,
            }

        except Exception as e:
            duration_ms = int((time.monotonic() - start_ms) * 1000)
            logger.error(f"[Replay] Failed for ride {ride_id}: {e}", exc_info=True)

            # Store failure
            try:
                self._client.table("replay_ride_results").upsert(
                    {
                        "batch_id": batch_id,
                        "ride_id": ride_id,
                        "status": "failed",
                        "error": str(e)[:500],
                        "processed_at": datetime.now(timezone.utc).isoformat(),
                        "duration_ms": duration_ms,
                    },
                    on_conflict="batch_id,ride_id",
                ).execute()

                # Update batch failure counter — best-effort SQL increment
                self._client.rpc("increment_replay_progress", {
                    "p_batch_id": batch_id,
                    "p_is_success": False,
                }).execute()
            except Exception as inner:
                logger.warning(f"[Replay] Failed to record failure: {inner}")

            return {
                "ride_id": ride_id,
                "status": "failed",
                "error": str(e),
                "duration_ms": duration_ms,
            }

    # -----------------------------------------------------------------------
    # 3. generate_scorecard
    # -----------------------------------------------------------------------

    async def generate_scorecard(self, batch_id: str) -> Dict[str, Any]:
        """
        Generate summary statistics for a replay batch.

        Aggregates per-ride results into a human-reviewable scorecard
        showing how many metrics changed, climbs were added/removed,
        vault matches gained/lost, and total economic delta.

        Returns:
            Scorecard dict, also stored on the batch row.
        """
        # Fetch all completed results for this batch
        results = self._client.table("replay_ride_results").select(
            "ride_id, status, metrics, climbs, vault_matches, economic_delta, duration_ms"
        ).eq("batch_id", batch_id).execute()

        rows = results.data or []

        completed = [r for r in rows if r["status"] == "completed"]
        failed = [r for r in rows if r["status"] == "failed"]

        # Fetch all diffs for this batch
        diffs_result = self._client.table("ride_diffs").select(
            "has_metric_changes, has_climb_changes, has_match_changes, has_economic_changes, diff"
        ).eq("batch_id", batch_id).execute()
        diffs = diffs_result.data or []

        # Aggregate diff statistics
        rides_with_metric_changes = sum(1 for d in diffs if d.get("has_metric_changes"))
        rides_with_climb_changes = sum(1 for d in diffs if d.get("has_climb_changes"))
        rides_with_match_changes = sum(1 for d in diffs if d.get("has_match_changes"))
        rides_with_economic_changes = sum(1 for d in diffs if d.get("has_economic_changes"))

        # Calculate aggregate economic delta
        total_points_delta = 0.0
        total_tss_delta = 0.0
        total_climbs_added = 0
        total_climbs_removed = 0
        total_matches_added = 0
        total_matches_removed = 0

        for d in diffs:
            diff_data = d.get("diff", {})
            if not diff_data:
                continue

            metrics = diff_data.get("metrics", {})
            tss_info = metrics.get("tss", {})
            if isinstance(tss_info, dict):
                total_tss_delta += tss_info.get("delta", 0)

            climbs = diff_data.get("climbs", {})
            total_climbs_added += len(climbs.get("added", []))
            total_climbs_removed += len(climbs.get("removed", []))

            matches = diff_data.get("vault_matches", {})
            total_matches_added += len(matches.get("added", []))
            total_matches_removed += len(matches.get("removed", []))

            economic = diff_data.get("economic", {})
            points_info = economic.get("points_earned", {})
            if isinstance(points_info, dict):
                total_points_delta += points_info.get("delta", 0)

        # Calculate avg processing time
        durations = [r.get("duration_ms", 0) for r in completed if r.get("duration_ms")]
        avg_duration_ms = sum(durations) / len(durations) if durations else 0

        scorecard = {
            "total_rides": len(rows),
            "completed": len(completed),
            "failed": len(failed),
            "avg_duration_ms": round(avg_duration_ms),

            "rides_with_metric_changes": rides_with_metric_changes,
            "rides_with_climb_changes": rides_with_climb_changes,
            "rides_with_match_changes": rides_with_match_changes,
            "rides_with_economic_changes": rides_with_economic_changes,
            "rides_unchanged": len(completed) - len(diffs),

            "total_tss_delta": round(total_tss_delta, 2),
            "total_climbs_added": total_climbs_added,
            "total_climbs_removed": total_climbs_removed,
            "total_matches_added": total_matches_added,
            "total_matches_removed": total_matches_removed,
            "total_points_delta": round(total_points_delta, 2),
        }

        # Store scorecard on the batch
        self._client.table("replay_batches").update({
            "scorecard": scorecard,
            "status": "completed" if not failed else "completed",
            "completed_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", batch_id).execute()

        return scorecard

    # -----------------------------------------------------------------------
    # 4. generate_diff
    # -----------------------------------------------------------------------

    def generate_diff(
        self,
        ride_id: str,
        old_metrics: Dict[str, Any],
        new_metrics: Dict[str, Any],
        old_climbs: List[Dict] = None,
        new_climbs: List[Dict] = None,
        old_vault_matches: List[Dict] = None,
        new_vault_matches: List[Dict] = None,
        old_economic: Dict[str, Any] = None,
        new_economic: Dict[str, Any] = None,
    ) -> RideDiff:
        """
        Produce a structured diff comparing old vs new processing outputs.

        Returns:
            RideDiff with field-by-field comparison.
        """
        old_climbs = old_climbs or []
        new_climbs = new_climbs or []
        old_vault_matches = old_vault_matches or []
        new_vault_matches = new_vault_matches or []
        old_economic = old_economic or {}
        new_economic = new_economic or {}

        diff = RideDiff(ride_id=ride_id)

        # --- Metric diffs ---
        metric_keys = [
            "tss", "normalized_power_w", "elevation_gain_m", "distance_m",
            "duration_sec", "avg_power_w", "avg_hr_bpm", "kcals",
        ]
        for key in metric_keys:
            old_val = old_metrics.get(key)
            new_val = new_metrics.get(key)
            if old_val is None and new_val is None:
                continue
            old_num = float(old_val) if old_val is not None else 0
            new_num = float(new_val) if new_val is not None else 0
            delta = new_num - old_num
            pct = (delta / old_num * 100) if old_num != 0 else (100 if delta != 0 else 0)
            diff.metrics[key] = {
                "old": old_num,
                "new": new_num,
                "delta": round(delta, 2),
                "pct": round(pct, 2),
            }

        # --- Climb diffs ---
        old_sig_set = {
            c.get("signature_v2_hex") or c.get("signature_hex", f"idx-{i}")
            for i, c in enumerate(old_climbs)
        }
        new_sig_set = {
            c.get("signature_v2_hex") or c.get("signature_hex", f"idx-{i}")
            for i, c in enumerate(new_climbs)
        }

        # Build lookup maps
        old_by_sig = {}
        for i, c in enumerate(old_climbs):
            sig = c.get("signature_v2_hex") or c.get("signature_hex", f"idx-{i}")
            old_by_sig[sig] = c
        new_by_sig = {}
        for i, c in enumerate(new_climbs):
            sig = c.get("signature_v2_hex") or c.get("signature_hex", f"idx-{i}")
            new_by_sig[sig] = c

        added_sigs = new_sig_set - old_sig_set
        removed_sigs = old_sig_set - new_sig_set
        common_sigs = old_sig_set & new_sig_set

        added_climbs = []
        for sig in added_sigs:
            c = new_by_sig.get(sig, {})
            added_climbs.append({
                "vert_m": c.get("vert_m", 0),
                "time_s": c.get("time_s", 0),
                "avg_gradient_pct": c.get("avg_gradient_pct", 0),
                "road_name": c.get("road_name"),
                "reason": "Detected by new pipeline version",
            })

        removed_climbs = []
        for sig in removed_sigs:
            c = old_by_sig.get(sig, {})
            removed_climbs.append({
                "vert_m": c.get("vert_m", 0),
                "time_s": c.get("time_s", 0),
                "avg_gradient_pct": c.get("avg_gradient_pct", 0),
                "road_name": c.get("road_name"),
                "reason": "Not detected by new pipeline version",
            })

        modified_climbs = []
        for sig in common_sigs:
            old_c = old_by_sig.get(sig, {})
            new_c = new_by_sig.get(sig, {})
            changes = {}
            for field_name in ("vert_m", "time_s", "distance_m", "avg_gradient_pct"):
                ov = old_c.get(field_name)
                nv = new_c.get(field_name)
                if ov is not None and nv is not None and abs(float(ov) - float(nv)) > 0.01:
                    changes[field_name] = {
                        "old": float(ov),
                        "new": float(nv),
                        "delta": round(float(nv) - float(ov), 2),
                    }
            if changes:
                changes["signature_hex"] = sig
                changes["reason"] = "Boundary or measurement changes in new version"
                modified_climbs.append(changes)

        diff.climbs = {
            "count": {
                "old": len(old_climbs),
                "new": len(new_climbs),
                "delta": len(new_climbs) - len(old_climbs),
            },
            "added": added_climbs,
            "removed": removed_climbs,
            "modified": modified_climbs,
        }

        # --- Vault match diffs ---
        old_match_set = {
            m.get("vault_signature") or m.get("vault_name", f"match-{i}")
            for i, m in enumerate(old_vault_matches)
        }
        new_match_set = {
            m.get("vault_signature") or m.get("vault_name", f"match-{i}")
            for i, m in enumerate(new_vault_matches)
        }

        old_match_by_key = {}
        for i, m in enumerate(old_vault_matches):
            key = m.get("vault_signature") or m.get("vault_name", f"match-{i}")
            old_match_by_key[key] = m
        new_match_by_key = {}
        for i, m in enumerate(new_vault_matches):
            key = m.get("vault_signature") or m.get("vault_name", f"match-{i}")
            new_match_by_key[key] = m

        added_matches = []
        for key in new_match_set - old_match_set:
            m = new_match_by_key.get(key, {})
            added_matches.append({
                "vault_name": m.get("vault_name", key),
                "similarity": m.get("similarity", 0),
                "reason": "Matched by new pipeline version",
            })

        removed_matches = []
        for key in old_match_set - new_match_set:
            m = old_match_by_key.get(key, {})
            removed_matches.append({
                "vault_name": m.get("vault_name", key),
                "similarity": m.get("similarity", 0),
                "reason": "No longer matched by new pipeline version",
            })

        diff.vault_matches = {
            "count": {
                "old": len(old_vault_matches),
                "new": len(new_vault_matches),
                "delta": len(new_vault_matches) - len(old_vault_matches),
            },
            "added": added_matches,
            "removed": removed_matches,
        }

        # --- Economic diffs ---
        for key in ("points_earned", "cal_earned", "cal_tribute_total", "vault_completions"):
            old_val = old_economic.get(key)
            new_val = new_economic.get(key)
            if old_val is None and new_val is None:
                continue
            old_num = float(old_val) if old_val is not None else 0
            new_num = float(new_val) if new_val is not None else 0
            delta = new_num - old_num
            diff.economic[key] = {
                "old": old_num,
                "new": new_num,
                "delta": round(delta, 2),
            }

        return diff

    # -----------------------------------------------------------------------
    # 5. generate_explanation
    # -----------------------------------------------------------------------

    def generate_explanation(self, diff: Dict[str, Any]) -> str:
        """
        Produce a plain-English narrative from a structured diff.

        Suitable for showing to non-technical users or in
        dispute resolution contexts.
        """
        parts: List[str] = []

        # Metric changes
        metrics = diff.get("metrics", {})
        tss = metrics.get("tss", {})
        if isinstance(tss, dict) and tss.get("delta", 0) != 0:
            parts.append(
                f"TSS changed from {tss['old']:.1f} to {tss['new']:.1f} "
                f"({tss['delta']:+.1f}, {tss['pct']:+.1f}%)."
            )

        np_info = metrics.get("normalized_power_w", {})
        if isinstance(np_info, dict) and np_info.get("delta", 0) != 0:
            parts.append(
                f"Normalized power changed from {np_info['old']:.0f}W to "
                f"{np_info['new']:.0f}W ({np_info['delta']:+.0f}W)."
            )

        elev = metrics.get("elevation_gain_m", {})
        if isinstance(elev, dict) and abs(elev.get("delta", 0)) >= 1:
            parts.append(
                f"Elevation gain changed from {elev['old']:.0f}m to "
                f"{elev['new']:.0f}m ({elev['delta']:+.0f}m)."
            )

        # Climb changes
        climbs = diff.get("climbs", {})
        added = climbs.get("added", [])
        removed = climbs.get("removed", [])
        modified = climbs.get("modified", [])

        if added:
            names = []
            for c in added:
                name = c.get("road_name") or f"{c.get('vert_m', 0):.0f}m climb"
                names.append(f"{name}: +{c.get('vert_m', 0):.0f}m")
            parts.append(
                f"{len(added)} climb{'s' if len(added) != 1 else ''} "
                f"added ({', '.join(names)})."
            )

        if removed:
            names = []
            for c in removed:
                name = c.get("road_name") or f"{c.get('vert_m', 0):.0f}m climb"
                names.append(name)
            parts.append(
                f"{len(removed)} climb{'s' if len(removed) != 1 else ''} "
                f"removed ({', '.join(names)})."
            )

        if modified:
            parts.append(
                f"{len(modified)} climb{'s' if len(modified) != 1 else ''} "
                f"had boundary changes."
            )

        # Vault match changes
        matches = diff.get("vault_matches", {})
        m_added = matches.get("added", [])
        m_removed = matches.get("removed", [])

        if m_added:
            names = [m.get("vault_name", "unknown") for m in m_added]
            parts.append(
                f"{len(m_added)} vault match{'es' if len(m_added) != 1 else ''} "
                f"gained ({', '.join(names)})."
            )

        if m_removed:
            names = [m.get("vault_name", "unknown") for m in m_removed]
            parts.append(
                f"{len(m_removed)} vault match{'es' if len(m_removed) != 1 else ''} "
                f"lost ({', '.join(names)})."
            )

        # Economic changes
        economic = diff.get("economic", {})
        points_info = economic.get("points_earned", {})
        if isinstance(points_info, dict) and points_info.get("delta", 0) != 0:
            delta = points_info["delta"]
            parts.append(
                f"Points delta: {delta:+.1f} points "
                f"(from {points_info['old']:.0f} to {points_info['new']:.0f})."
            )

        if not parts:
            return "No changes detected."

        return " ".join(parts)

    # -----------------------------------------------------------------------
    # 6. promote_batch (disabled until implemented)
    # -----------------------------------------------------------------------

    async def promote_batch(self, batch_id: str, reviewed_by: str) -> Dict[str, Any]:
        """
        Validate that a replay batch could be promoted, then stop.

        Promotion remains intentionally disabled until we have real,
        audited semantics for applying staged replay results to production
        tables and the economic ledger.
        """
        # Verify batch exists and is in promotable state
        batch_result = self._client.table("replay_batches").select(
            "id, status, dry_run"
        ).eq("id", batch_id).limit(1).execute()

        if not batch_result.data:
            raise ValueError(f"Batch {batch_id} not found")

        batch = batch_result.data[0]

        if batch.get("dry_run"):
            raise ValueError("Cannot promote a dry-run batch")

        if batch.get("status") not in ("completed",):
            raise ValueError(
                f"Cannot promote batch in status '{batch.get('status')}'. "
                "Batch must be 'completed' first."
            )

        logger.info(
            "[Replay] Promotion requested for batch %s by %s, but replay "
            "promotion is disabled until the production cutover semantics are implemented",
            batch_id,
            reviewed_by,
        )

        raise NotImplementedError(
            "Replay batch promotion is disabled until production promotion "
            "semantics are implemented."
        )

    # -----------------------------------------------------------------------
    # Get batch status
    # -----------------------------------------------------------------------

    async def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Fetch a replay batch by ID, including progress and scorecard."""
        result = self._client.table("replay_batches").select("*").eq(
            "id", batch_id
        ).limit(1).execute()

        if not result.data:
            return None

        batch = result.data[0]

        # Fetch per-ride result summary
        rides_result = self._client.table("replay_ride_results").select(
            "ride_id, status, duration_ms, error"
        ).eq("batch_id", batch_id).execute()

        batch["ride_results"] = rides_result.data or []
        return batch

    # -----------------------------------------------------------------------
    # Run all rides in a batch
    # -----------------------------------------------------------------------

    async def run_batch(self, batch_id: str) -> Dict[str, Any]:
        """
        Process all rides in a batch sequentially.

        For current scale (<3K rides), sequential processing is acceptable.
        At larger scale, this should be replaced with concurrent workers.
        """
        batch = await self.get_batch(batch_id)
        if not batch:
            raise ValueError(f"Batch {batch_id} not found")

        ride_ids = batch.get("ride_ids") or []
        if not ride_ids:
            raise ValueError(f"Batch {batch_id} has no ride IDs")

        results = {"completed": 0, "failed": 0, "total": len(ride_ids)}

        for ride_id in ride_ids:
            result = await self.replay_ride(batch_id, ride_id)
            if result.get("status") == "completed":
                results["completed"] += 1
            else:
                results["failed"] += 1

        # Generate scorecard after all rides are processed
        scorecard = await self.generate_scorecard(batch_id)
        results["scorecard"] = scorecard

        return results

    # -----------------------------------------------------------------------
    # Internal helpers
    # -----------------------------------------------------------------------

    async def _get_rides_for_wallet(self, wallet: str) -> List[str]:
        """Fetch all ride IDs for a wallet."""
        user_repo = create_user_repository()

        # Look up user by wallet to get user_id
        user_id = await user_repo.get_user_id(wallet)
        if not user_id:
            return []

        result = self._client.table("rides").select("id").eq(
            "user_id", user_id
        ).eq("processing_status", "completed").execute()

        return [r["id"] for r in (result.data or [])]

    async def _get_profile_snapshot(
        self, ride_id: str, user_id: Optional[str] = None,
    ) -> tuple[float, int]:
        """
        Get the frozen historical denominator or current derived Threshold.

        Prefers the snapshot captured at original processing time.
        A pre-cutover frozen snapshot remains replayable. New work never falls
        back to a declared profile value or an unfrozen 200 W denominator.
        """
        # Try snapshot first
        snapshot_result = self._client.table("user_profile_snapshots").select(
            "weight_kg, ftp_watts"
        ).eq("reference_type", "ride").eq(
            "reference_id", ride_id
        ).order("created_at", desc=True).limit(1).execute()

        if snapshot_result.data:
            snap = snapshot_result.data[0]
            weight = float(snap.get("weight_kg") or 75.0)
            frozen_threshold = snap.get("ftp_watts")
            if frozen_threshold is None:
                raise RuntimeError(
                    "Replay snapshot has no established Threshold denominator"
                )
            ftp = int(frozen_threshold)
            return weight, ftp

        # Fallback: current derived Threshold. The ordinary profile read stays
        # independent so an authority outage cannot block ride admission.
        if user_id:
            user_repo = create_user_repository()
            user = await user_repo.get_user_by_id(user_id)
            if user:
                projection = parse_threshold_rider_projection(
                    await create_ride_repository().get_reward_threshold_rider_projection(
                        user_id
                    )
                )
                if projection.state != "established":
                    raise RuntimeError(
                        "Replay requires an established derived Threshold"
                    )
                weight = float(user.get("weight_kg") or 75.0)
                return weight, projection.training_denominator.watts

        raise RuntimeError("Replay lacks a frozen or derived Threshold denominator")

    async def _run_pipeline(
        self,
        raw_bytes: bytes,
        file_type: str,
        user_weight_kg: float,
        user_ftp_w: int,
        reward_ftp_w: Optional[int],
    ) -> Dict[str, Any]:
        """
        Run the processing pipeline on raw file bytes.

        Returns a dict with metrics, climbs, and vault_matches for comparison.
        Does NOT write to production tables.
        """
        import os

        # Parse the file
        _rust_mode = os.getenv("USE_RUST_PARSER", "auto").strip().lower()
        _rust_disabled = _rust_mode in ("0", "false", "no", "off")

        if _rust_disabled:
            from .ride_parser import parse_ride_file
            file_data_b64 = base64.b64encode(raw_bytes).decode("utf-8")
            parsed_ride = parse_ride_file(file_data_b64, file_type)
        else:
            try:
                from .workout_parse_adapter import (
                    parse_ride_file_bytes_rust as parse_bytes,
                )
                parsed_ride = parse_bytes(raw_bytes, file_type)
            except ImportError:
                from .ride_parser import parse_ride_file
                file_data_b64 = base64.b64encode(raw_bytes).decode("utf-8")
                parsed_ride = parse_ride_file(file_data_b64, file_type)

        if not parsed_ride.records:
            raise ValueError("No valid records found in file")

        # Calculate metrics
        from .ride_metrics import calculate_metrics
        metrics = calculate_metrics(
            records=parsed_ride.records,
            user_weight_kg=user_weight_kg,
            user_ftp_w=user_ftp_w,
        )
        economic_metrics = None
        if reward_ftp_w is not None:
            economic_metrics = (
                metrics
                if reward_ftp_w == user_ftp_w
                else calculate_metrics(
                    records=parsed_ride.records,
                    user_weight_kg=user_weight_kg,
                    user_ftp_w=reward_ftp_w,
                )
            )

        metrics_dict = metrics.to_dict() if hasattr(metrics, "to_dict") else metrics.__dict__

        # Project to tiles and detect patterns
        from .tile_service import TileService
        from .pattern_engine import PatternEngine, UserProfile

        tile_service = TileService()

        # Convert records to GPS points for tile projection
        record_points = []
        for rec in parsed_ride.records:
            lat = getattr(rec, "lat", None) or (rec.get("lat") if isinstance(rec, dict) else None)
            lon = getattr(rec, "lon", None) or (rec.get("lon") if isinstance(rec, dict) else None)
            ts = getattr(rec, "timestamp", None) or (rec.get("timestamp") if isinstance(rec, dict) else None)

            if lat is None or lon is None or ts is None:
                continue

            elevation_m = getattr(rec, "elevation_m", None) or (rec.get("elevation_m") if isinstance(rec, dict) else None)
            power_w = getattr(rec, "power_w", None) or (rec.get("power_w") if isinstance(rec, dict) else None)
            hr_bpm = getattr(rec, "heart_rate_bpm", None) or getattr(rec, "hr_bpm", None)
            if hr_bpm is None and isinstance(rec, dict):
                hr_bpm = rec.get("hr_bpm") or rec.get("heart_rate_bpm")
            speed_mps = getattr(rec, "speed_mps", None) or (rec.get("speed_mps") if isinstance(rec, dict) else None)

            record_points.append({
                "timestamp": ts,
                "lat": lat,
                "lon": lon,
                "elevation_m": elevation_m,
                "power_w": power_w,
                "hr_bpm": hr_bpm,
                "speed_mps": speed_mps,
            })

        record_points.sort(key=lambda p: p["timestamp"])

        climbs_list = []
        vault_matches_list = []

        if record_points:
            tile_samples = tile_service.get_tile_sequence(
                gps_points=record_points,
                resolution=10,
            )

            if tile_samples:
                tile_dicts = [
                    {
                        "tile_id": s.tile_id,
                        "t": int(s.t),
                        "elevation_m": s.elevation_m,
                        "power_w": s.power_w,
                        "hr_bpm": s.hr_bpm,
                        "lat": s.lat,
                        "lon": s.lon,
                    }
                    for s in tile_samples
                ]

                user_profile = UserProfile(
                    wallet="replay-staging",
                    weight_kg=user_weight_kg,
                    ftp_w=user_ftp_w,
                )

                pattern_engine = PatternEngine()

                from uuid import uuid4
                patterns = await pattern_engine.detect_patterns(
                    activity_id=uuid4(),
                    tile_samples=tile_dicts,
                    user_profile=user_profile,
                    wallet_tile_history=set(),
                )

                if patterns and patterns.climb_patterns:
                    climbs_list = [p.to_dict() for p in patterns.climb_patterns]

                if patterns and patterns.vault_completions:
                    vault_matches_list = [
                        {
                            "vault_id": vc.vault_id,
                            "vault_name": vc.vault_name,
                            "similarity": vc.similarity,
                        }
                        for vc in patterns.vault_completions
                    ]

        # Build economic summary
        economic_tss = (
            float(economic_metrics.tss or 0)
            if economic_metrics is not None
            else None
        )
        economic = {
            "points_earned": economic_tss,
            "reward_tss": economic_tss,
            "reward_ftp_w": reward_ftp_w,
            "reward_ftp_authority": (
                "ride_snapshot" if reward_ftp_w is not None else "legacy_unknown"
            ),
            "vault_completions": len(vault_matches_list),
        }

        return {
            "metrics": metrics_dict,
            "climbs": climbs_list,
            "vault_matches": vault_matches_list,
            "economic": economic,
        }

    async def _fetch_original_outputs(
        self, ride_id: str, ride: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Fetch original processing outputs from production tables for comparison.
        """
        # Metrics from rides table
        metrics = {
            "tss": ride.get("tss"),
            "normalized_power_w": ride.get("normalized_power_w"),
            "elevation_gain_m": ride.get("elevation_gain_m"),
            "distance_m": ride.get("distance_m"),
            "duration_sec": ride.get("duration_sec"),
            "avg_power_w": ride.get("avg_power_w"),
            "avg_hr_bpm": ride.get("avg_hr_bpm"),
            "kcals": ride.get("kcals"),
        }

        # Climbs from patterns_climb
        climbs_result = self._client.table("patterns_climb").select(
            "vert_m, time_s, distance_m, avg_gradient_pct, road_name, "
            "signature_hex, signature_v2_hex, economic_eligible"
        ).eq("activity_id", ride_id).execute()

        climbs = climbs_result.data or []

        # Vault matches (completions) — uses activity_id, not ride_id
        vault_matches = []
        try:
            completions_result = self._client.table("vault_completions").select(
                "vault_signature"
            ).eq("activity_id", ride_id).execute()

            for vc in (completions_result.data or []):
                vault_matches.append({
                    "vault_signature": vc.get("vault_signature"),
                    "vault_name": vc.get("vault_signature", "")[:16],
                })
        except Exception:
            pass  # vault_completions table may not exist or ride has no completions

        # Economic
        economic = {
            "points_earned": float(ride.get("points_earned") or ride.get("tss") or 0),
            "vault_completions": len(vault_matches),
        }

        return {
            "metrics": metrics,
            "climbs": climbs,
            "vault_matches": vault_matches,
            "economic": economic,
        }


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def get_replay_service(client=None) -> ReplayService:
    """Create a ReplayService instance."""
    return ReplayService(client=client)
