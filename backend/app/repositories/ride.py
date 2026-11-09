"""Ride repository - rides, GPS tracks, and activity streams."""
from __future__ import annotations

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from ..services.ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    resolve_policy,
)
from ..services.ride_provenance_policy import provider_import_source_aliases
from ..services.training_eligibility import COUNTED_STATUSES
from ..utils.postgrest_paging import PageCursor, order_by, window
from .base import BaseRepository

logger = logging.getLogger(__name__)


class RideRepository(BaseRepository):
    """Repository for ride and activity stream operations."""

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    async def _get_default_ride_privacy(self, user_id: str) -> Dict[str, Any]:
        """Fetch the complete future-ride default without inventing exposure."""
        try:
            response = await self._run(
                lambda: self._client.table("users")
                .select(
                    "default_ride_visibility,default_map_visibility,"
                    "default_map_hide_start_m,default_map_hide_end_m"
                )
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            raise PrivacySettingsUnavailable(
                "privacy defaults unavailable"
            ) from exc
        row = self._first_row(response)
        if not row:
            raise PrivacySettingsUnavailable("privacy defaults unavailable")
        return row

    async def resolve_ride_privacy_policy(
        self,
        user_id: str,
        *,
        visibility: Optional[str] = None,
        map_visibility: Optional[str] = None,
        map_hide_start_m: Optional[int] = None,
        map_hide_end_m: Optional[int] = None,
    ) -> RidePrivacyPolicy:
        """Freeze explicit overrides over the rider's complete account default."""
        defaults = await self._get_default_ride_privacy(user_id)
        overrides = {
            key: value
            for key, value in {
                "visibility": visibility,
                "map_visibility": map_visibility,
                "map_hide_start_m": map_hide_start_m,
                "map_hide_end_m": map_hide_end_m,
            }.items()
            if value is not None
        }
        return resolve_policy(defaults, overrides)

    async def create_ride(
        self,
        user_id: str,
        status: str = "pending",
        file_type: Optional[str] = None,
        ride_id: Optional[str] = None,
        started_at: Optional[str] = None,
        tss: float = 0,
        kcals: float = 0,
        duration_sec: int = 0,
        # Raw file storage fields
        raw_file_path: Optional[str] = None,
        raw_file_size_bytes: Optional[int] = None,
        file_hash: Optional[str] = None,
        upload_verified_at: Optional[datetime] = None,
        preliminary_ride_hash_hex: Optional[str] = None,
        preliminary_parser_version: Optional[int] = None,
        import_source: Optional[str] = None,
        import_source_id: Optional[str] = None,
        import_diagnostics: Optional[Dict[str, Any]] = None,
        visibility: Optional[str] = None,
        map_visibility: Optional[str] = None,
        map_hide_start_m: Optional[int] = None,
        map_hide_end_m: Optional[int] = None,
        privacy_policy: Optional[RidePrivacyPolicy] = None,
    ) -> str:
        """Create a new ride record."""
        ride_id = ride_id or str(uuid.uuid4())
        policy = privacy_policy or await self.resolve_ride_privacy_policy(
            user_id,
            visibility=visibility,
            map_visibility=map_visibility,
            map_hide_start_m=map_hide_start_m,
            map_hide_end_m=map_hide_end_m,
        )
        if not isinstance(policy, RidePrivacyPolicy):
            raise PrivacySettingsUnavailable("ride privacy policy unavailable")
        payload = {
            "id": ride_id,
            "user_id": user_id,
            "tss": float(tss),
            "kcals": float(kcals),
            "duration_sec": int(duration_sec),
            "started_at": started_at or datetime.now(timezone.utc).isoformat(),
            "processing_status": status,
            "file_type": file_type,
            "created_at": datetime.now(timezone.utc).isoformat(),
            **policy.to_storage_dict(),
        }
        # Add storage fields if provided
        if raw_file_path:
            payload["raw_file_path"] = raw_file_path
            payload["uploaded_at"] = datetime.now(timezone.utc).isoformat()
        if raw_file_size_bytes is not None:
            payload["raw_file_size_bytes"] = raw_file_size_bytes
        if file_hash:
            payload["file_hash"] = file_hash
        if upload_verified_at is not None:
            verified_at = (
                upload_verified_at.replace(tzinfo=timezone.utc)
                if upload_verified_at.tzinfo is None
                else upload_verified_at.astimezone(timezone.utc)
            )
            payload["upload_verified_at"] = verified_at.isoformat()
        if preliminary_ride_hash_hex:
            payload["preliminary_ride_hash_hex"] = preliminary_ride_hash_hex
        if preliminary_parser_version is not None:
            payload["preliminary_parser_version"] = preliminary_parser_version
        if import_source:
            payload["import_source"] = import_source
        if import_source_id:
            payload["import_source_id"] = import_source_id
        if import_diagnostics:
            payload["import_diagnostics"] = import_diagnostics

        await self._run(lambda: self._client.table("rides").insert(payload).execute())
        return ride_id

    async def get_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        """Get a ride by ID."""
        response = await self._run(
            lambda: self._client.table("rides")
            .select("*")
            .eq("id", ride_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def bind_reward_ftp_snapshot(
        self,
        *,
        ride_id: uuid.UUID,
        activity_started_at: Optional[datetime],
    ) -> Optional[Dict[str, Any]]:
        """Bind or load the immutable service-authorized FTP for one ride."""
        started_at = activity_started_at
        if started_at is not None:
            started_at = (
                started_at.replace(tzinfo=timezone.utc)
                if started_at.tzinfo is None
                else started_at.astimezone(timezone.utc)
            )
        response = await self._run(
            lambda: self._client.rpc(
                "bind_ride_reward_ftp",
                {
                    "p_ride_id": str(ride_id),
                    "p_activity_started_at": (
                        started_at.isoformat() if started_at is not None else None
                    ),
                },
            ).execute()
        )
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            return dict(data)
        return self._first_row(response)

    async def register_reward_threshold_effort(
        self,
        *,
        ride_id: uuid.UUID,
        best_180s_w: Optional[float],
        best_420s_w: Optional[float],
        best_900s_w: Optional[float],
    ) -> Optional[Dict[str, Any]]:
        """Append one ride's immutable Threshold anchors and promotion decision."""
        if best_180s_w is None and best_420s_w is None and best_900s_w is None:
            raise ValueError("Threshold evidence requires at least one power anchor")
        response = await self._run(
            lambda: self._client.rpc(
                "register_reward_threshold_effort",
                {
                    "p_ride_id": str(ride_id),
                    "p_best_180s_w": best_180s_w,
                    "p_best_420s_w": best_420s_w,
                    "p_best_900s_w": best_900s_w,
                },
            ).execute()
        )
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            return dict(data)
        return self._first_row(response)

    async def seal_due_reward_threshold_promotions(self) -> int:
        """Seal every due Monday Threshold version through the private RPC."""
        response = await self._run(
            lambda: self._client.rpc(
                "seal_due_reward_threshold_promotions", {}
            ).execute()
        )
        data = getattr(response, "data", None)
        if isinstance(data, int):
            return data
        if isinstance(data, list) and data:
            value = data[0]
            if isinstance(value, dict):
                value = next(iter(value.values()), 0)
            return int(value or 0)
        return int(data or 0)

    async def get_reward_threshold_rider_projection(
        self,
        user_id: str,
    ) -> Dict[str, Any]:
        """Read the service-only rider Threshold authority projection."""
        response = await self._run(
            lambda: self._client.rpc(
                "get_reward_threshold_rider_projection",
                {"p_user_id": str(user_id)},
            ).execute(),
            operation="get_reward_threshold_rider_projection",
        )
        data = getattr(response, "data", None)
        if not isinstance(data, dict):
            raise RuntimeError("Threshold authority returned no rider projection")
        return dict(data)

    async def get_reward_threshold_ride_projections(
        self,
        ride_ids: List[str],
    ) -> Dict[str, Dict[str, Any]]:
        """Read release-aware Threshold money states without an N+1 query."""
        if not ride_ids:
            return {}
        response = await self._run(
            lambda: self._client.rpc(
                "get_reward_threshold_ride_projections",
                {"p_ride_ids": [str(ride_id) for ride_id in ride_ids]},
            ).execute(),
            operation="get_reward_threshold_ride_projections",
        )
        data = getattr(response, "data", None)
        if not isinstance(data, dict):
            raise RuntimeError("Threshold authority returned no ride projection")
        return {
            str(ride_id): dict(value)
            for ride_id, value in data.items()
            if isinstance(value, dict)
        }

    async def find_ride_by_import_identity(
        self,
        user_id: str,
        import_source: str,
        import_source_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Find a ride by normalized provider activity identity."""
        source_id = str(import_source_id or "").strip()
        source_aliases = sorted(provider_import_source_aliases(import_source))
        if not source_id or not source_aliases:
            return None

        def _query():
            query = (
                self._client.table("rides")
                .select("*")
                .eq("user_id", str(user_id))
                .eq("import_source_id", source_id)
            )
            if len(source_aliases) == 1:
                query = query.eq("import_source", source_aliases[0])
            else:
                query = query.in_("import_source", source_aliases)
            return query.order("created_at", desc=True).limit(1).execute()

        response = await self._run(_query)
        return self._first_row(response)

    async def update_ride_status(
        self,
        ride_id: uuid.UUID,
        status: str,
        error_message: Optional[str] = None,
        **metrics: Any,
    ) -> None:
        """Update ride processing status and optional metrics."""
        update_data: Dict[str, Any] = {"processing_status": status}
        if error_message is not None:
            update_data["error_message"] = error_message
        elif status != "failed":
            update_data["error_message"] = None
        update_data.update(metrics)
        await self._run(
            lambda: self._client.table("rides")
            .update(update_data)
            .eq("id", str(ride_id))
            .execute()
        )

    async def transition_ride_status(
        self,
        ride_id: uuid.UUID,
        *,
        expected_status: str,
        new_status: str,
        error_message: Optional[str] = None,
        **extra_fields: Any,
    ) -> bool:
        """Conditionally advance one ride only while its durable state matches."""
        unsupported = set(extra_fields) - {"upload_verified_at"}
        if unsupported:
            raise ValueError(
                "unsupported ride transition field(s): "
                + ", ".join(sorted(unsupported))
            )
        update_data: Dict[str, Any] = {"processing_status": new_status}
        if error_message is not None:
            update_data["error_message"] = error_message
        elif new_status != "failed":
            update_data["error_message"] = None
        update_data.update(extra_fields)

        response = await self._run(
            lambda: self._client.table("rides")
            .update(update_data)
            .eq("id", str(ride_id))
            .eq("processing_status", expected_status)
            .execute()
        )
        return bool(getattr(response, "data", None) or [])

    async def update_ride_metadata(
        self,
        ride_id: str,
        updates: Dict[str, Any],
    ) -> None:
        """Update ride metadata (title, description, visibility, etc.)."""
        if not updates:
            return
        await self._run(
            lambda: self._client.table("rides")
            .update(updates)
            .eq("id", ride_id)
            .execute()
        )

    async def create_ride_media(
        self,
        *,
        media_id: str,
        ride_id: str,
        user_id: str,
        storage_path: str,
        file_name: Optional[str],
        mime_type: str,
        size_bytes: int,
        sort_order: int = 0,
        role: str = "photo",
    ) -> Dict[str, Any]:
        """Create a pending ride media row before direct storage upload."""
        payload = {
            "id": media_id,
            "ride_id": ride_id,
            "user_id": user_id,
            "storage_path": storage_path,
            "file_name": file_name,
            "mime_type": mime_type,
            "size_bytes": int(size_bytes),
            "sort_order": int(sort_order),
            "role": role,
            "upload_status": "uploading",
            "moderation_state": "visible",
        }
        response = await self._run(
            lambda: self._client.table("ride_media").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_ride_media(self, media_id: str) -> Optional[Dict[str, Any]]:
        """Fetch one ride media row."""
        response = await self._run(
            lambda: self._client.table("ride_media")
            .select("*")
            .eq("id", media_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def list_ride_media(
        self,
        ride_id: str,
        *,
        include_uploading: bool = False,
    ) -> List[Dict[str, Any]]:
        """List visible media for a ride in display order."""
        def _query():
            query = (
                self._client.table("ride_media")
                .select("*")
                .eq("ride_id", ride_id)
                .neq("moderation_state", "hidden")
                .neq("moderation_state", "removed")
            )
            query = order_by(query, "sort_order", "created_at")
            if not include_uploading:
                query = query.eq("upload_status", "ready")
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def list_ride_media_for_rides(
        self,
        ride_ids: List[str],
        *,
        include_uploading: bool = False,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """List visible media for many rides in one query."""
        unique_ids = [str(ride_id) for ride_id in dict.fromkeys(ride_ids) if ride_id]
        grouped: Dict[str, List[Dict[str, Any]]] = {ride_id: [] for ride_id in unique_ids}
        if not unique_ids:
            return grouped

        def _query():
            query = (
                self._client.table("ride_media")
                .select("*")
                .in_("ride_id", unique_ids)
                .neq("moderation_state", "hidden")
                .neq("moderation_state", "removed")
            )
            query = order_by(query, "ride_id", "sort_order", "created_at")
            if not include_uploading:
                query = query.eq("upload_status", "ready")
            return query.execute()

        response = await self._run(_query)
        for row in getattr(response, "data", None) or []:
            ride_id = str(row.get("ride_id") or "")
            if ride_id in grouped:
                grouped[ride_id].append(dict(row))
        return grouped

    async def mark_ride_media_ready(
        self,
        media_id: str,
        *,
        size_bytes: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark a media upload as ready and return the updated row."""
        update_data: Dict[str, Any] = {
            "upload_status": "ready",
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        if size_bytes is not None:
            update_data["size_bytes"] = int(size_bytes)
        response = await self._run(
            lambda: self._client.table("ride_media")
            .update(update_data)
            .eq("id", media_id)
            .execute()
        )
        return self._first_row(response)

    async def complete_ride_media_upload(
        self,
        media_id: str,
        *,
        ride_id: str,
        storage_path: str,
        size_bytes: int,
        width: int,
        height: int,
        mime_type: str = "image/jpeg",
    ) -> Optional[Dict[str, Any]]:
        """Atomically mark an upload ready and preserve one visible cover."""
        response = await self._run(
            lambda: self._client.rpc(
                "complete_sanitized_ride_media_upload",
                {
                    "p_media_id": media_id,
                    "p_ride_id": ride_id,
                    "p_size_bytes": size_bytes,
                    "p_storage_path": storage_path,
                    "p_width": width,
                    "p_height": height,
                    "p_mime_type": mime_type,
                },
            ).execute()
        )
        return self._first_row(response)

    async def update_ride_media(
        self,
        media_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Update owner-managed ride media fields."""
        clean_updates = {key: value for key, value in updates.items() if value is not None}
        if not clean_updates:
            return await self.get_ride_media(media_id)
        clean_updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = await self._run(
            lambda: self._client.table("ride_media")
            .update(clean_updates)
            .eq("id", media_id)
            .execute()
        )
        return self._first_row(response)

    async def set_ride_media_cover(
        self,
        *,
        ride_id: str,
        media_id: str,
    ) -> Optional[Dict[str, Any]]:
        """Make one visible ready media row the ride cover."""
        response = await self._run(
            lambda: self._client.rpc(
                "set_ride_media_cover",
                {
                    "p_ride_id": ride_id,
                    "p_media_id": media_id,
                },
            ).execute()
        )
        return self._first_row(response)

    async def reorder_ride_media(
        self,
        ride_id: str,
        order: Dict[str, int],
    ) -> List[Dict[str, Any]]:
        """Update display order for a ride's media rows and return visible media."""
        now = datetime.now(timezone.utc).isoformat()
        for media_id, sort_order in order.items():
            await self._run(
                lambda media_id=media_id, sort_order=sort_order: self._client.table("ride_media")
                .update({"sort_order": int(sort_order), "updated_at": now})
                .eq("id", media_id)
                .eq("ride_id", ride_id)
                .execute()
            )
        return await self.list_ride_media(ride_id)

    async def mark_ride_media_failed(self, media_id: str) -> None:
        """Mark a media upload as failed."""
        await self._run(
            lambda: self._client.table("ride_media")
            .update({
                "upload_status": "failed",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            })
            .eq("id", media_id)
            .execute()
        )

    async def mark_ride_media_moderated(
        self,
        media_id: str,
        *,
        moderation_state: str,
        moderated_by: Optional[str] = None,
        moderation_report_id: Optional[str] = None,
        moderation_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Apply a moderation visibility state to a ride media row."""
        payload = {
            "moderation_state": moderation_state,
            "moderated_at": datetime.now(timezone.utc).isoformat(),
            "moderated_by": moderated_by,
            "moderation_report_id": moderation_report_id,
            "moderation_reason": moderation_reason,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("ride_media")
            .update(payload)
            .eq("id", media_id)
            .execute()
        )
        return self._first_row(response)

    async def list_stale_ride_media_uploads(
        self,
        *,
        older_than: str,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List stale non-ready media rows for storage cleanup."""
        response = await self._run(
            lambda: self._client.table("ride_media")
            .select("*")
            .in_("upload_status", ["uploading", "failed"])
            .lte("updated_at", older_than)
            .order("updated_at", desc=False)
            .limit(limit)
            .execute()
        )
        return [dict(row) for row in getattr(response, "data", None) or []]

    async def delete_ride_media(self, media_id: str) -> None:
        """Delete a ride media row."""
        await self._run(
            lambda: self._client.table("ride_media")
            .delete()
            .eq("id", media_id)
            .execute()
        )

    async def delete_ride(self, ride_id: str) -> None:
        """Delete a ride by ID."""
        await self._run(
            lambda: self._client.table("rides")
            .delete()
            .eq("id", ride_id)
            .execute()
        )

    async def list_rides_for_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """List all rides for a user, most recent first."""
        safe_limit = max(1, min(int(limit), 100))
        safe_offset = max(0, int(offset))
        # Exactly safe_limit rows: clients stop paging on a short page.
        response = await self._run(
            lambda: window(
                self._client.table("rides")
                .select("*")
                .eq("user_id", user_id)
                .order("started_at", desc=True),
                safe_offset,
                safe_limit,
            ).execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def list_counted_climb_steps(
        self, rides: List[Dict[str, Any]],
    ) -> Dict[str, List[Dict[str, Any]]]:
        """At most two page-wide reads; never query streams per ride.

        Ordinary plans and released hold snapshots are distinct authorities.
        Missing/incomplete authority produces no counted strokes.
        """
        completed = [row for row in rides if row.get("processing_status") == "completed"]
        released_ids = [str(row["id"]) for row in completed
                        if row.get("threshold_economy_state") == "counted"]
        ordinary_ids = [str(row["id"]) for row in completed
                        if str(row["id"]) not in released_ids
                        and row.get("reward_policy") != "threshold_provisional_hold_v1"]
        result: Dict[str, List[Dict[str, Any]]] = {}
        if ordinary_ids:
            response = await self._run(
                lambda: self._client.table("ride_economic_plans").select(
                    "ride_id,state,exact_cal_base_units,"
                    "steps:ride_economic_completion_steps("
                    "segment_start_offset_s,segment_end_offset_s,exact_tribute_base_units,pattern_id)"
                ).in_("ride_id", ordinary_ids).eq("state", "complete").execute(),
                operation="list_counted_climb_steps",
            )
            for plan in getattr(response, "data", None) or []:
                if plan.get("state") == "complete" and int(plan.get("exact_cal_base_units") or 0) > 0:
                    result[str(plan["ride_id"])] = plan.get("steps") or []
        if released_ids:
            response = await self._run(
                lambda: self._client.table("reward_threshold_release_snapshots").select(
                    "ride_id,exact_cal_base_units,snapshot_evidence,"
                    "execution:reward_threshold_release_executions(state,terminal_projected_at)"
                ).in_("ride_id", released_ids).execute(),
                operation="list_released_climb_steps",
            )
            for snapshot in getattr(response, "data", None) or []:
                execution = snapshot.get("execution") or {}
                if (execution.get("state") == "complete" and execution.get("terminal_projected_at")
                        and int(snapshot.get("exact_cal_base_units") or 0) > 0):
                    result[str(snapshot["ride_id"])] = (snapshot.get("snapshot_evidence") or {}).get("steps") or []
        return result

    async def bind_training_inputs(self, ride_id, user_id, started_at, evidence):
        self._check_training_boundary(ride_id)
        response = await self._run(lambda: self._client.rpc("bind_ride_training_inputs", {
            "p_ride_id": str(ride_id), "p_user_id": str(user_id),
            "p_started_at": started_at.isoformat(), "p_evidence": evidence,
        }).execute())
        return response.data

    async def claim_training_replay(self, limit=10):
        from ..services.training_metrics import ENGINE_VERSION

        runtime = getattr(self, "training_runtime", None)
        response = await self._run(lambda: self._client.rpc("claim_training_replay", {
            "p_limit": limit,
            "p_startup_cutoff": runtime.startup_cutoff if runtime else None,
            "p_excluded_ids": sorted(r for r in runtime.blocked_rides if r) if runtime else [],
            "p_engine_version": ENGINE_VERSION,
        }).execute())
        return response.data or []

    def _check_training_boundary(self, ride_id):
        runtime = getattr(self, "training_runtime", None)
        if runtime is not None and str(ride_id) in runtime.blocked_rides:
            raise RuntimeError("training payment attempt active")

    async def training_replay_startup_cutoff(self):
        response = await self._run(lambda: self._client.rpc("training_replay_startup_cutoff", {}).execute())
        return response.data

    async def set_training_pay_attempt(self, ride_id, user_id, token, finished):
        await self._run(lambda: self._client.rpc("set_training_pay_attempt", {
            "p_ride_id": str(ride_id), "p_user_id": str(user_id),
            "p_token": token, "p_finished": finished,
        }).execute())

    async def finish_training_replay(self, ride_id, user_id, error_class=None, *, scoring_inputs=None):
        from ..services.training_metrics import ENGINE_VERSION

        await self._run(lambda: self._client.rpc("finish_training_replay", {
            "p_ride_id": str(ride_id), "p_user_id": str(user_id), "p_error_class": error_class,
            "p_engine_version": ENGINE_VERSION,
            "p_scoring_inputs": {
                key: scoring_inputs.get(key)
                for key in ("raw_file_path", "started_at", "file_type")
            } if scoring_inputs is not None else None,
        }).execute())

    async def training_climb_patterns(self, ride_id):
        response = await self._run(lambda: self._client.table("patterns_climb")
            .select("id,start_offset_s,end_offset_s,avg_power_w,w_per_kg,"
                    "time_s,detector_version,match_trace")
            .eq("activity_id", str(ride_id)).execute())
        return response.data or []

    async def store_climb_efforts(self, ride_id, user_id, inputs, efforts):
        self._check_training_boundary(ride_id)
        await self._run(lambda: self._client.rpc("store_climb_efforts", {
            "p_ride_id": str(ride_id), "p_user_id": str(user_id),
            "p_inputs": inputs, "p_efforts": efforts,
        }).execute())

    async def store_training_metrics(self, ride_id, user_id, inputs, metrics, evidence):
        self._check_training_boundary(ride_id)
        response = await self._run(lambda: self._client.rpc("store_ride_training_metrics", {
            "p_ride_id": str(ride_id), "p_user_id": str(user_id), "p_inputs": inputs,
            "p_metrics": metrics, "p_evidence": evidence,
        }).execute())
        return response.data

    async def current_training_threshold(self, user_id):
        response = await self._run(lambda: self._client.rpc("current_training_threshold", {
            "p_user_id": str(user_id), "p_as_of": datetime.now(timezone.utc).isoformat(),
        }).execute())
        return response.data

    async def training_settings(self, user_id):
        response = await self._run(lambda: self._client.table("users")
            .select("training_settings_history").eq("id", str(user_id)).single().execute())
        history = response.data.get("training_settings_history") or []
        return history[-1]["settings"] if history else {}

    async def append_training_settings(self, user_id, settings):
        response = await self._run(lambda: self._client.rpc("append_training_settings", {
            "p_user_id": str(user_id), "p_settings": settings,
        }).execute())
        return response.data

    async def initialize_training_timezone(self, user_id, timezone_name):
        response = await self._run(lambda: self._client.rpc("initialize_training_timezone", {
            "p_user_id": str(user_id), "p_timezone": timezone_name,
        }).execute())
        return response.data

    async def list_threshold_training_rides(
        self,
        user_id: str,
        *,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
    ) -> List[Dict[str, Any]]:
        """Read every denominator-independent input needed for training views."""
        rows: List[Dict[str, Any]] = []
        page_size = 1000
        pages = PageCursor(page_size)
        while True:
            def _query():
                query = (
                    self._client.table("rides")
                    .select(
                        "id,started_at,processing_status,duration_sec,tss,"
                        "normalized_power_w,normalized_power_raw_w,"
                        "normalized_power_duration_s,"
                        "threshold_training_kind,training_metrics,raw_file_path,training_error,training_replay_state(error_class)"
                    )
                    .eq("user_id", str(user_id))
                    .in_("processing_status", sorted(COUNTED_STATUSES))
                )
                query = order_by(query, "started_at", "id")
                if start_date is not None:
                    query = query.gte(
                        "started_at",
                        datetime.combine(
                            start_date - timedelta(days=1),
                            datetime.min.time(),
                            tzinfo=timezone.utc,
                        ).isoformat(),
                    )
                if end_date is not None:
                    query = query.lte(
                        "started_at",
                        datetime.combine(
                            end_date + timedelta(days=1),
                            datetime.max.time(),
                            tzinfo=timezone.utc,
                        ).isoformat(),
                    )
                return query.range(
                    pages.offset,
                    pages.offset + page_size - 1,
                ).execute()

            response = await self._run(
                _query,
                operation="list_threshold_training_rides",
            )
            page = [
                dict(row)
                for row in (getattr(response, "data", None) or [])
                if isinstance(row, dict)
            ]
            rows.extend(page)
            if not pages.advance(page):  # range() is end-exclusive; see postgrest_paging.
                break
        return rows

    async def get_global_rides(
        self,
        limit: int = 20,
        before: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent public rides from all users for global feed."""
        def _query():
            query = (
                self._client.table("rides")
                .select("*")
                .eq("visibility", "public")
                .neq("processing_status", "failed")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if before:
                query = query.lt("created_at", before.isoformat())
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_user_rides_for_date(
        self, user_id: str, ride_date: date
    ) -> List[Dict[str, Any]]:
        """Get all rides for a user on a specific date."""
        start_of_day = datetime.combine(ride_date, datetime.min.time(), tzinfo=timezone.utc)
        end_of_day = datetime.combine(ride_date, datetime.max.time(), tzinfo=timezone.utc)

        response = await self._run(
            lambda: self._client.table("rides")
            .select("*")
            .eq("user_id", user_id)
            .gte("started_at", start_of_day.isoformat())
            .lte("started_at", end_of_day.isoformat())
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def store_activity_stream(
        self,
        ride_id: uuid.UUID,
        stream_type: str,
        timestamps: List[datetime],
        values: List[float],
    ) -> uuid.UUID:
        """Store an activity data stream (power, HR, etc.)."""
        sample_count = len(values)
        min_val = min(values) if values else None
        max_val = max(values) if values else None
        avg_val = (sum(values) / len(values)) if values else None
        payload = {
            "ride_id": str(ride_id),
            "stream_type": stream_type,
            "timestamps": [t.isoformat() for t in timestamps],
            "values": values,
            "sample_count": sample_count,
            "min_value": min_val,
            "max_value": max_val,
            "avg_value": avg_val,
        }
        response = await self._run(
            lambda: self._client.table("activity_streams")
            .upsert(payload, on_conflict="ride_id,stream_type")
            .execute()
        )
        data = getattr(response, "data", None) or []
        stream_id = data[0].get("id") if data else None
        return uuid.UUID(stream_id) if stream_id else uuid.uuid4()

    async def get_activity_stream(
        self,
        ride_id: uuid.UUID,
        stream_type: str,
    ) -> Optional[Dict]:
        """Get an activity stream by ride and type."""
        response = await self._run(
            lambda: self._client.table("activity_streams")
            .select("*")
            .eq("ride_id", str(ride_id))
            .eq("stream_type", stream_type)
            .maybe_single()
            .execute()
        )
        data = getattr(response, "data", None)
        return dict(data) if data else None

    async def store_gps_points(
        self,
        ride_id: uuid.UUID,
        points: List[Dict],
    ) -> int:
        """Store GPS points as polyline-encoded track in rides.gps_track."""
        if not points:
            return 0

        from ..utils.polyline import encode_gps_track

        # Convert points to format expected by encoder
        records = [
            {
                "sequence_num": i,
                "timestamp": p["timestamp"].isoformat() if hasattr(p.get("timestamp"), "isoformat") else p.get("timestamp"),
                "latitude": p["latitude"],
                "longitude": p["longitude"],
                "elevation_m": p.get("elevation"),
                "distance_m": p.get("distance"),
            }
            for i, p in enumerate(points)
        ]

        # Encode to polyline format
        encoded = encode_gps_track(records)
        # ISO timestamps are compressed relative to the first GPS point, which
        # can occur after ride start. Preserve that clock origin for frozen
        # climb-window projections without changing any existing stream values.
        if isinstance(records[0].get("timestamp"), str):
            try:
                origin = datetime.fromisoformat(records[0]["timestamp"].replace("Z", "+00:00"))
                if origin.tzinfo is not None:
                    encoded["time_origin"] = origin.isoformat()
            except ValueError:
                pass

        # Store in rides.gps_track
        response = await self._run(
            lambda: self._client.table("rides")
            .update({"gps_track": encoded})
            .eq("id", str(ride_id))
            .execute()
        )

        data = getattr(response, "data", None) or []
        return len(points) if data else 0

    async def get_gps_track(
        self,
        ride_id: uuid.UUID,
        limit: int = 50000,
    ) -> List[Dict]:
        """Fetch GPS track from rides.gps_track polyline-encoded column."""
        from ..utils.polyline import decode_gps_track

        response = await self._run(
            lambda: self._client.table("rides")
            .select("gps_track")
            .eq("id", str(ride_id))
            .execute()
        )
        data = getattr(response, "data", None) or []
        if not data or not data[0].get("gps_track"):
            return []

        encoded = data[0]["gps_track"]
        points = decode_gps_track(encoded)
        return points[:limit]

    async def store_canon_traversal_evidence(
        self,
        row: Dict[str, Any],
    ) -> None:
        """Idempotently persist the private, identity-bound D11 sample stream."""
        await self._run(
            lambda: self._client.table("canon_traversal_evidence")
            .upsert(
                dict(row),
                returning="minimal",
                on_conflict=(
                    "ride_id,ride_hash_hex,ride_parser_version,evidence_version"
                ),
            )
            .execute()
        )

    async def get_canon_traversal_evidence(
        self,
        *,
        ride_id: uuid.UUID,
        ride_hash_hex: str,
        ride_parser_version: int,
        evidence_version: str,
    ) -> Optional[Dict[str, Any]]:
        """Load only the D11 stream for the ride's current attested identity."""
        response = await self._run(
            lambda: self._client.table("canon_traversal_evidence")
            .select(
                "ride_id,ride_hash_hex,ride_parser_version,evidence_version,"
                "sample_count,sample_digest,samples"
            )
            .eq("ride_id", str(ride_id))
            .eq("ride_hash_hex", str(ride_hash_hex).lower())
            .eq("ride_parser_version", int(ride_parser_version))
            .eq("evidence_version", evidence_version)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_ride_segment_efforts(self, ride_id: uuid.UUID) -> List[Dict[str, Any]]:
        """Get all segment efforts for a ride."""
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("ride_id", str(ride_id))
            .order("elapsed_time_sec")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # --- Raw File Storage Methods ---

    async def find_ride_by_hash(
        self,
        user_id: str,
        file_hash: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Find a ride by user and file hash for deduplication.

        Args:
            user_id: User's UUID
            file_hash: SHA256 hash of file content

        Returns:
            Ride dict if found, None otherwise
        """
        rides = await self.find_rides_by_hash(user_id, file_hash, limit=1)
        return rides[0] if rides else None

    async def find_rides_by_hash(
        self,
        user_id: str,
        file_hash: str,
        *,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Find rides by user and file hash for deduplication, newest first.

        Args:
            user_id: User's UUID
            file_hash: SHA256 hash of file content
            limit: Maximum number of matching rows to return

        Returns:
            Matching ride rows ordered by uploaded_at desc.
        """
        response = await self._run(
            lambda: self._client.table("rides")
                .select("id, uploaded_at, processing_status, file_name, file_type, raw_file_path")
            .eq("user_id", user_id)
            .eq("file_hash", file_hash)
            .order("uploaded_at", desc=True)
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def increment_reprocess_count(self, ride_id: str) -> None:
        """
        Increment the reprocess counter for a ride.

        Uses a database function for atomic increment.
        """
        await self._run(
            lambda: self._client.rpc(
                "increment_ride_reprocess",
                {"p_ride_id": ride_id}
            ).execute()
        )

    async def clear_ride_error(self, ride_id: str) -> None:
        """Clear error message when reprocessing a ride."""
        await self._run(
            lambda: self._client.table("rides")
            .update({"error_message": None})
            .eq("id", ride_id)
            .execute()
        )

    # --- Phase Processing Methods ---

    async def update_phase_status(
        self,
        ride_id: uuid.UUID,
        phase: int,
        success: bool,
        error_message: Optional[str] = None,
        duration_ms: Optional[int] = None,
        **extra_fields: Any,
    ) -> None:
        """
        Update ride processing phase status.

        Args:
            ride_id: Ride UUID
            phase: Phase number (1, 2, or 3)
            success: Whether the phase completed successfully
            error_message: Error message if phase failed
            duration_ms: Phase processing duration in milliseconds
            **extra_fields: Additional fields to update (metrics, etc.)
        """
        update_data: Dict[str, Any] = {}

        if phase == 1:
            if success:
                update_data["processing_status"] = "metrics_ready"
                update_data["phase1_completed_at"] = datetime.now(timezone.utc).isoformat()
                update_data["phase1_error"] = None
                update_data["error_message"] = None
            else:
                update_data["processing_status"] = "failed"
                update_data["phase1_error"] = error_message
                update_data["error_message"] = error_message
            if duration_ms is not None:
                update_data["phase1_duration_ms"] = duration_ms

        elif phase == 2:
            if success:
                update_data["processing_status"] = "enriched"
                update_data["phase2_completed_at"] = datetime.now(timezone.utc).isoformat()
                update_data["phase2_error"] = None
                update_data["error_message"] = None
            else:
                # Phase 2 failure doesn't change overall status
                update_data["phase2_error"] = error_message
            if duration_ms is not None:
                update_data["phase2_duration_ms"] = duration_ms

        elif phase == 3:
            if success:
                update_data["processing_status"] = "completed"
                update_data["phase3_completed_at"] = datetime.now(timezone.utc).isoformat()
                update_data["phase3_error"] = None
                update_data["error_message"] = None
            else:
                # Phase 3 failure doesn't change overall status
                update_data["phase3_error"] = error_message
            if duration_ms is not None:
                update_data["phase3_duration_ms"] = duration_ms

        # Add any extra fields (metrics, etc.)
        update_data.update(extra_fields)
        # The release snapshot requires the raw normalized-power value and its
        # exact duration as one atomic pair. workout-parse represents an
        # unpowered ride as (None, 0); persist that absence as (NULL, NULL) so
        # ordinary no-power rides satisfy the database invariant.
        if (
            "normalized_power_raw_w" in update_data
            or "normalized_power_duration_s" in update_data
        ) and update_data.get("normalized_power_raw_w") is None:
            update_data["normalized_power_duration_s"] = None

        await self._run(
            lambda: self._client.table("rides")
            .update(update_data)
            .eq("id", str(ride_id))
            .execute()
        )

    async def get_ride_for_phase2(self, ride_id: str) -> Optional[Dict[str, Any]]:
        """
        Get ride data needed for Phase 2 processing.

        Returns ride with user_id, file_type, and Phase 1 metrics.
        """
        response = await self._run(
            lambda: self._client.table("rides")
            .select(
                "id, user_id, file_type, processing_status, "
                "training_metrics, tss, kcals, distance_m, elevation_gain_m, duration_sec, moving_time_sec, "
                "economic_tss, reward_ftp_w, reward_ftp_source, "
                "reward_ftp_authority_id, reward_ftp_policy_version, "
                "threshold_training_w, threshold_training_kind, "
                "threshold_training_authority_id, threshold_training_promotion_id, "
                "metrics_version, power_sample_count, power_sample_coverage_bps, "
                "heart_rate_sample_count, heart_rate_sample_coverage_bps, "
                "avg_power_w, normalized_power_w, normalized_power_raw_w, "
                "normalized_power_duration_s, avg_hr_bpm, started_at, completed_at, "
                "effort_evidence_tier, reward_policy, estimated_cal, rewardable_cal, "
                "tributable_cal, raw_file_path, ride_hash_hex, "
                "effort_spans_ms, effort_seconds, covered_effort_seconds, paid_effort_seconds, "
                "attestation_commitment_hex, ride_parser_version, "
                "canonical_match, review_reason"
            )
            .eq("id", ride_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_ride_for_phase3(self, ride_id: str) -> Optional[Dict[str, Any]]:
        """
        Get ride data needed for Phase 3 processing.

        Returns ride with user_id and metrics for rewards calculation.
        """
        response = await self._run(
            lambda: self._client.table("rides")
            .select(
                "id, user_id, processing_status, "
                "training_metrics, tss, kcals, distance_m, elevation_gain_m, duration_sec, moving_time_sec, "
                "economic_tss, reward_ftp_w, reward_ftp_source, "
                "reward_ftp_authority_id, reward_ftp_policy_version, "
                "threshold_training_w, threshold_training_kind, "
                "threshold_training_authority_id, threshold_training_promotion_id, "
                "metrics_version, power_sample_count, power_sample_coverage_bps, "
                "heart_rate_sample_count, heart_rate_sample_coverage_bps, "
                "avg_power_w, normalized_power_w, normalized_power_raw_w, "
                "normalized_power_duration_s, avg_hr_bpm, "
                "started_at, completed_at, file_type, ride_hash_hex, "
                "attestation_commitment_hex, ride_parser_version, "
                "ride_attestation_pda, ride_attestation_tx_signature, ride_attested_at, "
                "canonical_match, review_reason, "
                "effort_evidence_tier, reward_policy, estimated_cal, rewardable_cal, "
                "tributable_cal"
            )
            .eq("id", ride_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)
