from __future__ import annotations

import asyncio
import logging
import time
import uuid
import warnings
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from typing import Any, Dict, List, Optional, Sequence, Union

from supabase.lib.client_options import ClientOptions

from .config import load_supabase_settings
from .supabase_client import BackendSupabaseClient, create_backend_supabase_client
from .feed_contracts import FEED_CONTRACT_VERSION, infer_activity_event_type
from .moderation_contracts import (
    MODERATION_CONTRACT_VERSION,
    action_application_status,
    normalize_action_row,
    normalize_resolution_action,
    reporter_message_for,
    reporter_outcome_for,
)
from .notification_contracts import build_notification_insert
from .services.privacy_resolver import normalize_visibility
from .services.ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    resolve_policy,
)
from .utils.polyline import encode_gps_track, decode_gps_track
from .utils.postgrest_paging import order_by, window


logger = logging.getLogger(__name__)

FOLLOWING_IDS_CACHE_TTL_SECONDS = 15
USER_ROW_CACHE_TTL_SECONDS = 60

_following_ids_cache: Dict[str, tuple[float, List[str]]] = {}
_user_row_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}


def clear_user_row_cache(user_id: str) -> None:
    """Clear cached public user rows after profile/avatar mutations."""
    _user_row_cache.pop(str(user_id), None)


class DatabaseRepository(ABC):
    @abstractmethod
    async def create_user(self, wallet: str, email: Optional[str] = None) -> str: ...

    @abstractmethod
    async def get_user_id(self, wallet: str) -> Optional[str]: ...

    @abstractmethod
    async def get_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]: ...

    # Social graph
    @abstractmethod
    async def create_follow(self, follower_id: str, following_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def delete_follow(self, follower_id: str, following_id: str) -> bool: ...

    @abstractmethod
    async def get_follow(self, follower_id: str, following_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_following_ids(self, user_id: str) -> List[str]: ...

    # Activity feed
    @abstractmethod
    async def create_activity(
        self,
        user_id: str,
        activity_type: str,
        title: str,
        description: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_public: bool = True,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_feed_activities(self, user_ids: List[str], limit: int = 20, before: Optional[datetime] = None) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_global_activities(
        self,
        limit: int = 20,
        before: Optional[datetime] = None,
        activity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...

    # Notifications
    @abstractmethod
    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: Optional[str],
        data: Optional[Dict[str, Any]] = None,
        *,
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
        delivery_channels: Optional[Sequence[str]] = None,
        dedupe_key: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_user_notifications(self, user_id: str, limit: int = 50, unread_only: bool = False) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_unread_notification_count(self, user_id: str) -> int: ...

    @abstractmethod
    async def mark_notification_read(self, notification_id: str, user_id: str) -> bool: ...

    @abstractmethod
    async def mark_all_notifications_read(self, user_id: str) -> int: ...

    @abstractmethod
    async def get_notification_preferences(self, user_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def upsert_notification_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]: ...

    # Comments & kudos
    @abstractmethod
    async def create_comment(
        self,
        user_id: str,
        target_type: str,
        target_id: str,
        content: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_comments(self, target_type: str, target_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def create_kudos(self, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_kudos(self, user_id: str, target_type: str, target_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def delete_kudos(self, user_id: str, target_type: str, target_id: str) -> bool: ...

    @abstractmethod
    async def increment_kudos_count(self, target_type: str, target_id: str) -> None: ...

    @abstractmethod
    async def decrement_kudos_count(self, target_type: str, target_id: str) -> None: ...

    async def create_social_report(
        self,
        reporter_id: str,
        target_type: str,
        target_id: str,
        reason: str,
        details: Optional[str] = None,
        moderation_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        raise NotImplementedError

    async def get_report_summaries(
        self,
        target_type: str,
        target_ids: List[str],
        reporter_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        return {
            str(target_id): {"viewerReported": False, "reportStatus": None, "reportId": None}
            for target_id in target_ids
            if target_id
        }

    async def list_social_reports(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def resolve_social_report(
        self,
        report_id: str,
        reviewer_id: str,
        status: str,
        resolution_note: Optional[str] = None,
        resolution_action: Optional[str] = None,
        reporter_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def list_user_social_reports(
        self,
        reporter_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def get_social_report_for_reporter(
        self,
        report_id: str,
        reporter_id: str,
    ) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    async def get_public_user_recent_rides(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError

    async def get_public_beetle_cards_for_wallet(self, wallet: str) -> List[Dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    async def update_cal_balance(self, user_id: str, amount: float) -> Dict[str, Any]: ...

    @abstractmethod
    async def record_cal_mint(self, user_id: str, amount: float, minted_at: datetime) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_user_ride_streak(self, user_id: str) -> int: ...

    @abstractmethod
    async def create_vesting_schedule(
        self,
        user_id: str,
        token_type: str,
        total_amount: int,
        end_date: datetime,
        source_type: Optional[str],
        source_id: Optional[str],
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_user_vesting_schedules(self, user_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_claims(self, user_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_claim(self, user_id: str, segment_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def upsert_claim(self, user_id: str, segment_id: str, amount: float, lp_tokens: float) -> None: ...

    @abstractmethod
    async def delete_claim(self, user_id: str, segment_id: str) -> None: ...

    @abstractmethod
    async def get_current_epoch(self, segment_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_epoch(self, segment_id: str, epoch_number: int) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_segment_epoch_activity(self, segment_id: str, epoch_number: int) -> Dict[str, Any]: ...

    @abstractmethod
    async def update_claim_harvest(self, user_id: str, segment_id: str, last_harvest_epoch: int) -> None: ...

    @abstractmethod
    async def create_harvest_event(
        self,
        user_id: str,
        segment_id: str,
        epoch_number: int,
        lp_tokens_held: float,
        dung_harvested: float,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_leaderboard(self, segment_id: str, epoch_number: int, limit: int = 100) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def create_token_transaction(
        self,
        user_id: str,
        tx_type: str,
        token_type: str,
        amount: float,
        balance_after: Optional[float],
        reference_type: Optional[str],
        reference_id: Optional[str],
        tx_signature: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        tx_type: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_all_user_transactions(self, user_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def list_rides_for_user(self, user_id: str) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def list_segments(
        self,
        bbox: Optional[tuple[float, float, float, float]] = None,
        query: Optional[str] = None,
        min_lat: Optional[float] = None,
        max_lat: Optional[float] = None,
        min_lon: Optional[float] = None,
        max_lon: Optional[float] = None,
    ) -> List[Dict[str, Any]]: ...

    @abstractmethod
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
        visibility: Optional[str] = None,
        map_visibility: Optional[str] = None,
        map_hide_start_m: Optional[int] = None,
        map_hide_end_m: Optional[int] = None,
        privacy_policy: Optional[RidePrivacyPolicy] = None,
    ) -> str: ...

    @abstractmethod
    async def get_ride(self, ride_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def update_ride_status(
        self,
        ride_id: uuid.UUID,
        status: str,
        error_message: Optional[str] = None,
        **metrics: Any,
    ) -> None: ...

    @abstractmethod
    async def update_ride_metadata(
        self,
        ride_id: str,
        updates: Dict[str, Any],
    ) -> None: ...

    @abstractmethod
    async def store_activity_stream(
        self,
        ride_id: uuid.UUID,
        stream_type: str,
        timestamps: List[datetime],
        values: List[float],
    ) -> uuid.UUID: ...

    @abstractmethod
    async def get_activity_stream(
        self,
        ride_id: uuid.UUID,
        stream_type: str,
    ) -> Optional[Dict]: ...

    @abstractmethod
    async def get_ride_segment_efforts(self, ride_id: uuid.UUID) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def store_gps_points(
        self,
        ride_id: uuid.UUID,
        points: List[Dict],
    ) -> int: ...

    @abstractmethod
    async def get_gps_track(
        self,
        ride_id: uuid.UUID,
        limit: int = 50000,
    ) -> List[Dict]: ...

    @abstractmethod
    async def store_activity_tile_samples(
        self,
        ride_id: uuid.UUID,
        tile_samples: List[Dict[str, Any]],
    ) -> int: ...

    @abstractmethod
    async def update_wallet_tile_history(
        self,
        user_id: uuid.UUID,
        tile_ids: List[str],
        visited_at: Optional[datetime] = None,
    ) -> int: ...

    @abstractmethod
    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_rides_for_date(self, user_id: str, ride_date: date) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def create_proof(
        self,
        ride_id: str,
        effort_score: float,
        signature: str = "",
        user_id: Optional[str] = None,
        proof_id: Optional[str] = None,
        dung_amount: Optional[float] = None,
        proof_hash: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str: ...

    @abstractmethod
    async def get_proof(self, proof_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_proof_for_ride(self, ride_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def proof_has_mint(self, proof_id: str) -> bool: ...

    @abstractmethod
    async def update_proof_status(self, proof_id: str, status: str, tx_signature: Optional[str]) -> None: ...

    @abstractmethod
    async def create_mint_event(
        self,
        proof_id: str,
        amount: float,
        tx_hash: str,
        status: str,
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def record_mint_event(
        self,
        user_id: str,
        ride_id: str,
        proof_id: str,
        dung_amount: float,
        tx_signature: Optional[str],
        status: str,
    ) -> Dict[str, Any]: ...

    @abstractmethod
    async def deduct_cal(self, user_id: str, amount: float) -> None: ...

    @abstractmethod
    async def refund_cal(self, user_id: str, amount: float) -> None: ...

    @abstractmethod
    async def update_proof_signature(self, proof_id: str, signature: str) -> None: ...

    @abstractmethod
    async def update_user_state(self, user_id: str, updates: Dict[str, Any]) -> None: ...

    @abstractmethod
    async def delete_ride(self, ride_id: str) -> None: ...

    @abstractmethod
    async def get_segment_by_id(self, segment_id: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_segment_pool(self, segment_id: str) -> Dict[str, float]: ...

    @abstractmethod
    async def create_segment_effort(
        self,
        ride_id: uuid.UUID,
        user_id: uuid.UUID,
        segment_id: Union[uuid.UUID, int],
        elapsed_time_sec: int,
        effort_score: float,
        average_power_w: Optional[float],
        average_hr_bpm: Optional[float],
        elevation_gain_m: Optional[float],
        distance_m: Optional[float],
        is_pr: bool,
        is_kom: bool,
        rank_at_time: Optional[int],
    ) -> uuid.UUID: ...

    @abstractmethod
    async def get_segment_best_effort(self, segment_id: Union[uuid.UUID, int]) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_best_segment_effort(self, user_id: uuid.UUID, segment_id: Union[uuid.UUID, int]) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_segment_effort_rank(self, segment_id: Union[uuid.UUID, int], elapsed_time_sec: int) -> Optional[int]: ...

    @abstractmethod
    async def get_user_max_power(self, user_id: uuid.UUID) -> Optional[float]: ...

    @abstractmethod
    async def get_user_total_distance(self, user_id: uuid.UUID) -> float: ...

    @abstractmethod
    async def get_user_total_elevation(self, user_id: uuid.UUID) -> float: ...

    @abstractmethod
    async def get_user_ride_count(self, user_id: uuid.UUID) -> int: ...

    @abstractmethod
    async def get_user_riding_streak(self, user_id: uuid.UUID) -> int: ...

    @abstractmethod
    async def get_user_wallet(self, user_id: uuid.UUID) -> Optional[str]: ...

    @abstractmethod
    async def health(self) -> bool: ...

    @abstractmethod
    async def get_token_balances(self, user_id: str) -> Dict[str, Any]: ...

    # Profile Hub methods
    @abstractmethod
    async def check_username_available(self, username: str) -> tuple[bool, Optional[str]]: ...

    @abstractmethod
    async def update_user_profile(self, wallet: str, updates: Dict[str, Any]) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]: ...

    @abstractmethod
    async def get_user_stats(self, user_id: str) -> Dict[str, Any]: ...

    @abstractmethod
    async def get_full_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]: ...

    # CAL airdrop methods
    @abstractmethod
    async def get_users_due_for_airdrop(self, limit: int = 100) -> List[Dict[str, Any]]: ...

    @abstractmethod
    async def process_cal_airdrop(self, user_id: str, amount: float) -> Dict[str, Any]: ...

    # Waitlist
    @abstractmethod
    async def add_to_waitlist(self, email: str, source: str, ip_hash: int) -> Dict[str, Any]: ...

    async def dispose(self) -> None:
        return None


class SupabaseRepository(DatabaseRepository):
    _FEED_ACTIVITY_SELECTION = (
        "id, user_id, activity_type, title, description, target_type, target_id, "
        "metadata, created_at, occurred_at, event_type, actor_id, visibility, "
        "schema_version, kudos_count"
    )
    _GLOBAL_RIDE_FEED_SELECTION = (
        "id, user_id, file_name, processing_status, started_at, created_at, "
        "distance_m, elevation_gain_m, elevation_corrected_gain_m, duration_sec, training_metrics, "
        "dung_minted, cal_earned, reward_policy, visibility, "
        "map_visibility, map_hide_start_m, map_hide_end_m, "
        "ride_hash_hex, attestation_commitment_hex, ride_attestation_pda, "
        "ride_attestation_tx_signature, ride_attested_at, finalized_at, "
        "moderation_state, moderated_at, moderated_by, moderation_report_id, "
        "gps_track"
    )
    _COMMENT_SELECTION = (
        "id, user_id, target_type, target_id, content, created_at, updated_at, parent_id, "
        "moderation_state, moderated_at, moderated_by, moderation_report_id"
    )

    def __init__(self, client: BackendSupabaseClient) -> None:
        self._client = client

    @property
    def client(self) -> BackendSupabaseClient:
        """Expose the Supabase client for direct queries (e.g., vault service)."""
        return self._client

    @staticmethod
    def _get_cached_value(cache: Dict[str, tuple[float, Any]], key: str, ttl_seconds: int) -> Any:
        cached = cache.get(key)
        now = time.monotonic()
        if not cached:
            return None
        cached_at, value = cached
        if now - cached_at >= ttl_seconds:
            cache.pop(key, None)
            return None
        return value

    @staticmethod
    def _set_cached_value(cache: Dict[str, tuple[float, Any]], key: str, value: Any) -> None:
        cache[key] = (time.monotonic(), value)

    @staticmethod
    def _comment_to_response(comment: Dict[str, Any], user: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        return {
            "id": comment.get("id"),
            "userId": comment.get("user_id"),
            "targetType": comment.get("target_type"),
            "targetId": comment.get("target_id"),
            "username": (user or {}).get("username"),
            "displayName": (user or {}).get("display_name"),
            "avatarUrl": (user or {}).get("avatar_url"),
            "avatar_storage_path": (user or {}).get("avatar_storage_path"),
            "avatar_mime_type": (user or {}).get("avatar_mime_type"),
            "avatar_size_bytes": (user or {}).get("avatar_size_bytes"),
            "isPublic": (user or {}).get("is_public"),
            "content": comment.get("content"),
            "createdAt": comment.get("created_at"),
            "updatedAt": comment.get("updated_at"),
            "parentId": comment.get("parent_id"),
            "moderationState": comment.get("moderation_state") or "visible",
            "moderatedAt": comment.get("moderated_at"),
            "moderatedBy": comment.get("moderated_by"),
            "moderationReportId": comment.get("moderation_report_id"),
        }

    @staticmethod
    def _social_report_to_response(report: Dict[str, Any]) -> Dict[str, Any]:
        reporter = report.get("reporter") or report.get("reporter_user") or {}
        reviewer = report.get("reviewer") or report.get("reviewer_user") or {}
        action_history = report.get("actionHistory") or report.get("action_history") or report.get("moderation_actions") or []
        return {
            "contractVersion": report.get("contract_version") or MODERATION_CONTRACT_VERSION,
            "id": report.get("id"),
            "reporterId": report.get("reporter_id"),
            "targetType": report.get("target_type"),
            "targetId": report.get("target_id"),
            "reason": report.get("reason"),
            "details": report.get("details"),
            "status": report.get("status"),
            "createdAt": report.get("created_at"),
            "updatedAt": report.get("updated_at"),
            "reviewedAt": report.get("reviewed_at"),
            "reviewedBy": report.get("reviewed_by"),
            "resolutionNote": report.get("resolution_note"),
            "resolutionAction": report.get("resolution_action"),
            "reporterOutcome": report.get("reporter_outcome"),
            "reporterMessage": report.get("reporter_message"),
            "moderationMetadata": report.get("moderation_metadata") or {},
            "actionHistory": [
                normalize_action_row(action)
                for action in action_history
                if isinstance(action, dict)
            ],
            "reporter": {
                "id": reporter.get("id"),
                "username": reporter.get("username"),
                "displayName": reporter.get("display_name"),
                "avatarUrl": reporter.get("avatar_url"),
            } if reporter else None,
            "reviewer": {
                "id": reviewer.get("id"),
                "username": reviewer.get("username"),
                "displayName": reviewer.get("display_name"),
                "avatarUrl": reviewer.get("avatar_url"),
            } if reviewer else None,
        }

    @staticmethod
    def _social_report_to_reporter_response(report: Dict[str, Any]) -> Dict[str, Any]:
        response = SupabaseRepository._social_report_to_response(report)
        response.pop("resolutionNote", None)
        response.pop("moderationMetadata", None)
        response.pop("actionHistory", None)
        response.pop("reviewer", None)
        return response

    async def create_user(self, wallet: str, email: Optional[str] = None) -> str:
        normalized_email = email.strip().lower() if email else None
        candidate_user_id = str(uuid.uuid4())
        response = await self._run(
            lambda: self._client.rpc(
                "br_get_or_create_active_user",
                {
                    "p_candidate_user_id": candidate_user_id,
                    "p_wallet": wallet,
                    "p_email": normalized_email,
                },
            ).execute()
        )
        rows = getattr(response, "data", None) or []
        row = dict(rows[0]) if rows else None
        if not row or not row.get("user_id"):
            raise RuntimeError("Active user authority returned no user")
        if bool(row.get("was_created")):
            from .metrics import KPI_USERS_CREATED

            KPI_USERS_CREATED.inc()
        return str(row["user_id"])

    async def get_user_id(self, wallet: str) -> Optional[str]:
        record = await self._fetch_user_by_wallet(wallet)
        if not record:
            return None
        return record.get("id")

    async def get_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("users")
            .select("id, wallet, email, created_at, weight_kg")
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def list_rides_for_user(self, user_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("*")
            .eq("user_id", user_id)
            .order("started_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_global_rides(
        self,
        limit: int = 20,
        before: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent public rides from all users for global feed."""
        def _query():
            query = (
                self._client.table("rides")
                .select(self._GLOBAL_RIDE_FEED_SELECTION)
                .eq("visibility", "public")
                .neq("processing_status", "failed")  # Exclude only failed rides
                .neq("moderation_state", "hidden")
                .neq("moderation_state", "removed")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if before:
                query = query.lt("created_at", before.isoformat())
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def list_segments(
        self,
        bbox: Optional[tuple[float, float, float, float]] = None,
        query: Optional[str] = None,
        min_lat: Optional[float] = None,
        max_lat: Optional[float] = None,
        min_lon: Optional[float] = None,
        max_lon: Optional[float] = None,
    ) -> List[Dict[str, Any]]:
        """DEPRECATED: Segment infrastructure has been replaced by pattern-based system.
        This method is kept for backwards compatibility with existing staking.
        Use pattern-based APIs instead.
        """
        import warnings
        warnings.warn(
            "list_segments is deprecated. Use pattern-based APIs instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        # Normalize bbox inputs (can come from tuple or explicit bounds)
        if bbox is None and all(v is not None for v in (min_lon, min_lat, max_lon, max_lat)):
            bbox = (min_lon, min_lat, max_lon, max_lat)  # type: ignore[assignment]

        if bbox or query or any(v is not None for v in (min_lat, max_lat, min_lon, max_lon)):
            params: Dict[str, Any] = {
                "west": bbox[0] if bbox else min_lon,
                "south": bbox[1] if bbox else min_lat,
                "east": bbox[2] if bbox else max_lon,
                "north": bbox[3] if bbox else max_lat,
                "name_query": query,
            }
            response = await self._run(
                lambda: self._client.rpc("segments_search", params).execute()
            )
        else:
            response = await self._run(
                lambda: self._client.table("segments").select("*").execute()
            )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

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
        visibility: Optional[str] = None,
        map_visibility: Optional[str] = None,
        map_hide_start_m: Optional[int] = None,
        map_hide_end_m: Optional[int] = None,
        privacy_policy: Optional[RidePrivacyPolicy] = None,
    ) -> str:
        ride_id = ride_id or str(uuid.uuid4())
        policy = privacy_policy
        if policy is None:
            default_response = await self._run(
                lambda: self._client.table("users")
                .select(
                    "default_ride_visibility,default_map_visibility,"
                    "default_map_hide_start_m,default_map_hide_end_m"
                )
                .eq("id", user_id)
                .limit(1)
                .execute()
            )
            default_row = self._first_row(default_response) or {}
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
            policy = resolve_policy(default_row, overrides)
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
        await self._run(lambda: self._client.table("rides").insert(payload).execute())
        return ride_id

    async def get_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("*")
            .eq("id", ride_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def update_ride_status(
        self,
        ride_id: uuid.UUID,
        status: str,
        error_message: Optional[str] = None,
        **metrics: Any,
    ) -> None:
        update_data: Dict[str, Any] = {"processing_status": status}
        if error_message:
            update_data["error_message"] = error_message
        update_data.update(metrics)
        await self._run(
            lambda: self._client.table("rides")
            .update(update_data)
            .eq("id", str(ride_id))
            .execute()
        )

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

    async def update_ride_media(
        self,
        media_id: str,
        updates: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
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
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "moderation_state": moderation_state,
            "moderated_at": now,
            "moderated_by": moderated_by,
            "moderation_report_id": moderation_report_id,
            "moderation_reason": moderation_reason,
            "updated_at": now,
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
        await self._run(
            lambda: self._client.table("ride_media")
            .delete()
            .eq("id", media_id)
            .execute()
        )

    async def store_activity_stream(
        self,
        ride_id: uuid.UUID,
        stream_type: str,
        timestamps: List[datetime],
        values: List[float],
    ) -> uuid.UUID:
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

    async def get_ride_segment_efforts(self, ride_id: uuid.UUID) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("ride_id", str(ride_id))
            .order("elapsed_time_sec")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def store_gps_points(
        self,
        ride_id: uuid.UUID,
        points: List[Dict],
    ) -> int:
        """Store GPS points as polyline-encoded track in rides.gps_track.

        Encodes GPS points using polyline compression (~92% size reduction)
        and stores as JSONB in the rides table instead of separate rows.

        Format stored:
        {
            "polyline": str,        # Encoded lat/lon
            "elevations": [int],    # Delta-encoded decimeters
            "timestamps": [int],    # Delta-encoded seconds
            "distances": [int],     # Delta-encoded meters
            "precision": int,
            "version": int
        }
        """
        if not points:
            return 0

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
        """Fetch GPS track from rides.gps_track polyline-encoded column.

        Decodes the polyline format back to individual GPS points.
        Much faster than row-per-point queries and no pagination needed.
        """
        response = await self._run(
            lambda: self._client.table("rides")
            .select("gps_track")
            .eq("id", str(ride_id))
            .execute()
        )

        data = getattr(response, "data", None) or []
        if not data or not data[0].get("gps_track"):
            return []

        # Decode polyline format back to points
        track_data = data[0]["gps_track"]
        points = decode_gps_track(track_data)

        return points[:limit]

    async def store_activity_tile_samples(
        self,
        ride_id: uuid.UUID,
        tile_samples: List[Dict[str, Any]],
    ) -> int:
        """
        Store H3 tile samples for an activity.

        Expected tile_sample format from TileService:
        {
            "tile_id": str,  # H3 index
            "t": int,  # seconds since ride start
            "lat": float,
            "lon": float,
            "elevation_m": Optional[float],
            "power_w": Optional[int],
            "hr_bpm": Optional[int],
            "speed_mps": Optional[float],
        }
        """
        if not tile_samples:
            return 0

        # Build all records first
        all_records = [
            {
                "activity_id": str(ride_id),
                "tile_id": sample["tile_id"],
                "t": sample.get("t", i),
                "elevation_m": sample.get("elevation_m"),
                "power_w": sample.get("power_w"),
                "hr_bpm": sample.get("hr_bpm"),
                "speed_mps": sample.get("speed_mps"),
            }
            for i, sample in enumerate(tile_samples)
        ]

        # Batch inserts to avoid Supabase row limits
        # Large rides (8+ hours) can have 20,000+ samples
        BATCH_SIZE = 1000
        total_inserted = 0

        for i in range(0, len(all_records), BATCH_SIZE):
            batch = all_records[i:i + BATCH_SIZE]
            response = await self._run(
                lambda batch=batch: self._client.table("activity_tile_samples").insert(batch).execute()
            )
            data = getattr(response, "data", None) or []
            total_inserted += len(data)

        return total_inserted

    async def update_wallet_tile_history(
        self,
        user_id: uuid.UUID,
        tile_ids: List[str],
        visited_at: Optional[datetime] = None,
    ) -> int:
        """
        Update wallet tile history for exploration tracking.
        Returns the count of new tiles explored.

        This method:
        1. Gets wallet address from user_id
        2. Checks which tiles are new for this wallet
        3. Inserts new tile records
        4. Returns count of newly explored tiles
        """
        if not tile_ids:
            return 0

        # Get wallet address from user
        user = await self.get_user_by_id(str(user_id))
        if not user or not user.get("wallet"):
            return 0

        wallet = user["wallet"]
        visited_timestamp = visited_at or datetime.now(timezone.utc)
        unique_tiles = list(set(tile_ids))  # Deduplicate

        # Check existing tiles for this wallet
        # Batch to avoid URL length limits (Supabase 400 error on large IN clauses)
        BATCH_SIZE = 200  # Safe limit for URL length
        existing_tile_ids: set = set()

        for i in range(0, len(unique_tiles), BATCH_SIZE):
            batch = unique_tiles[i:i + BATCH_SIZE]
            existing_response = await self._run(
                lambda batch=batch: self._client.table("wallet_tile_history")
                .select("tile_id")
                .eq("wallet", wallet)
                .in_("tile_id", batch)
                .execute()
            )
            existing_data = getattr(existing_response, "data", None) or []
            existing_tile_ids.update(row["tile_id"] for row in existing_data)

        # Find new tiles
        new_tiles = [tile_id for tile_id in unique_tiles if tile_id not in existing_tile_ids]

        if not new_tiles:
            return 0

        # Insert new tile history records in batches
        # Large rides (140mi+) can have 900+ new tiles
        INSERT_BATCH_SIZE = 500
        total_inserted = 0

        for i in range(0, len(new_tiles), INSERT_BATCH_SIZE):
            batch_tiles = new_tiles[i:i + INSERT_BATCH_SIZE]
            records = [
                {
                    "wallet": wallet,
                    "tile_id": tile_id,
                    "first_visited_at": visited_timestamp.isoformat(),
                    "visit_count": 1,
                }
                for tile_id in batch_tiles
            ]

            response = await self._run(
                lambda records=records: self._client.table("wallet_tile_history").insert(records).execute()
            )
            data = getattr(response, "data", None) or []
            total_inserted += len(data)

        return total_inserted

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        if not user_ids:
            return []

        unique_ids = [str(user_id) for user_id in dict.fromkeys(user_ids) if user_id]
        users_by_id: Dict[str, Dict[str, Any]] = {}
        missing_ids: List[str] = []

        for user_id in unique_ids:
            cached_user = self._get_cached_value(_user_row_cache, user_id, USER_ROW_CACHE_TTL_SECONDS)
            if cached_user is None:
                missing_ids.append(user_id)
            else:
                users_by_id[user_id] = dict(cached_user)

        if missing_ids:
            response = await self._run(
                lambda: self._client.table("users")
                .select("*")
                .in_("id", missing_ids)
                .execute()
            )
            for row in getattr(response, "data", None) or []:
                user = dict(row)
                user_id = str(user.get("id"))
                self._set_cached_value(_user_row_cache, user_id, user)
                users_by_id[user_id] = user

        return [users_by_id[user_id] for user_id in unique_ids if user_id in users_by_id]

    # Social graph
    async def create_follow(self, follower_id: str, following_id: str) -> Dict[str, Any]:
        payload = {"follower_id": follower_id, "following_id": following_id}
        response = await self._run(
            lambda: self._client.table("follows").insert(payload).execute()
        )
        _following_ids_cache.pop(str(follower_id), None)
        return self._first_row(response) or payload

    async def delete_follow(self, follower_id: str, following_id: str) -> bool:
        response = await self._run(
            lambda: self._client.table("follows")
            .delete()
            .eq("follower_id", follower_id)
            .eq("following_id", following_id)
            .execute()
        )
        _following_ids_cache.pop(str(follower_id), None)
        data = getattr(response, "data", None) or []
        return len(data) > 0

    async def get_follow(self, follower_id: str, following_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("follows")
            .select("*")
            .eq("follower_id", follower_id)
            .eq("following_id", following_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_followers(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: window(
                self._client.table("follows")
                .select("follower_id, users!follows_follower_id_fkey(*)")
                .eq("following_id", user_id)
                .order("followed_at", desc=True),
                offset,
                limit,
            ).execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row.get("users") or {}) for row in data]

    async def get_following(self, user_id: str, limit: int = 50, offset: int = 0) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: window(
                self._client.table("follows")
                .select("following_id, users!follows_following_id_fkey(*)")
                .eq("follower_id", user_id)
                .order("followed_at", desc=True),
                offset,
                limit,
            ).execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row.get("users") or {}) for row in data]

    async def get_following_ids(self, user_id: str) -> List[str]:
        cached_ids = self._get_cached_value(
            _following_ids_cache,
            str(user_id),
            FOLLOWING_IDS_CACHE_TTL_SECONDS,
        )
        if cached_ids is not None:
            return list(cached_ids)

        response = await self._run(
            lambda: self._client.table("follows")
            .select("following_id")
            .eq("follower_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        following_ids = [str(row.get("following_id")) for row in data if row.get("following_id")]
        self._set_cached_value(_following_ids_cache, str(user_id), following_ids)
        return following_ids

    # Activities / feed
    async def create_activity(
        self,
        user_id: str,
        activity_type: str,
        title: str,
        description: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        is_public: bool = True,
    ) -> Dict[str, Any]:
        event_type = infer_activity_event_type(activity_type, target_type).value
        payload = {
            "user_id": user_id,
            "actor_id": user_id,
            "activity_type": activity_type,
            "event_type": event_type,
            "title": title,
            "description": description,
            "target_type": target_type,
            "target_id": target_id,
            "metadata": metadata or {},
            "is_public": is_public,
            "visibility": "public" if is_public else "private",
            "schema_version": FEED_CONTRACT_VERSION,
        }
        response = await self._run(
            lambda: self._client.table("activities").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_feed_activities(self, user_ids: List[str], limit: int = 20, before: Optional[datetime] = None) -> List[Dict[str, Any]]:
        if not user_ids:
            return []

        def _query():
            query = (
                self._client.table("activities")
                .select(self._FEED_ACTIVITY_SELECTION)
                .in_("user_id", user_ids)
                .eq("is_public", True)
                .eq("moderation_state", "visible")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if before:
                query = query.lt("created_at", before.isoformat())
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_feed_rides(
        self,
        user_ids: List[str],
        limit: int = 20,
        before: Optional[datetime] = None,
    ) -> List[Dict[str, Any]]:
        """Get recent public/followers-visible rides from followed users."""
        if not user_ids:
            return []

        def _query():
            query = (
                self._client.table("rides")
                .select(self._GLOBAL_RIDE_FEED_SELECTION)
                .in_("user_id", user_ids)
                .in_("visibility", ["public", "followers"])
                .neq("processing_status", "failed")
                .neq("moderation_state", "hidden")
                .neq("moderation_state", "removed")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if before:
                query = query.lt("created_at", before.isoformat())
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_public_user_recent_rides(self, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("rides")
            .select(self._GLOBAL_RIDE_FEED_SELECTION)
            .eq("user_id", user_id)
            .eq("visibility", "public")
            .neq("processing_status", "failed")
            .neq("moderation_state", "hidden")
            .neq("moderation_state", "removed")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
        )
        return [dict(row) for row in getattr(response, "data", None) or []]

    async def get_public_beetle_cards_for_wallet(self, wallet: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("beetle_cards")
            .select("id, card_type, scope_id, score, level, patterns_scored, created_at, updated_at")
            .eq("wallet", wallet)
            .order("card_type")
            .execute()
        )
        cards = [dict(row) for row in getattr(response, "data", None) or []]
        arena_ids = [str(card.get("scope_id")) for card in cards if card.get("card_type") == "CLIMB"]
        arena_names: Dict[str, str] = {}
        if arena_ids:
            arenas_response = await self._run(
                lambda: self._client.table("arenas")
                .select("id, name")
                .in_("id", arena_ids)
                .execute()
            )
            arena_names = {
                str(row.get("id")): row.get("name")
                for row in getattr(arenas_response, "data", None) or []
                if row.get("id")
            }

        result = []
        for card in cards:
            card_type = card.get("card_type")
            scope_id = str(card.get("scope_id"))
            if card_type == "CLIMB":
                scope_name = arena_names.get(scope_id, "World Arena")
            else:
                scope_name = "Global"
            result.append({
                "id": card.get("id"),
                "cardType": card_type,
                "scopeId": scope_id,
                "scopeName": scope_name,
                "score": int(card.get("score") or 0),
                "level": int(card.get("level") or 0),
                "patternsScored": int(card.get("patterns_scored") or 0),
                "createdAt": card.get("created_at"),
                "updatedAt": card.get("updated_at"),
            })
        return result

    async def get_global_activities(
        self,
        limit: int = 20,
        before: Optional[datetime] = None,
        activity_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        def _query():
            query = (
                self._client.table("activities")
                .select("*")
                .eq("is_public", True)
                .eq("moderation_state", "visible")
                .order("created_at", desc=True)
                .limit(limit)
            )
            if before:
                query = query.lt("created_at", before.isoformat())
            if activity_type:
                query = query.eq("activity_type", activity_type)
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    # Notifications
    async def create_notification(
        self,
        user_id: str,
        notification_type: str,
        title: str,
        message: Optional[str],
        data: Optional[Dict[str, Any]] = None,
        *,
        actor_id: Optional[str] = None,
        target_type: Optional[str] = None,
        target_id: Optional[str] = None,
        occurred_at: Optional[str] = None,
        delivery_channels: Optional[Sequence[str]] = None,
        dedupe_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        user = await self.get_user_by_id(user_id)
        payload = build_notification_insert(
            user_id=user_id,
            wallet=user.get("wallet") if user else None,
            notification_type=notification_type,
            title=title,
            message=message,
            data=data,
            actor_id=actor_id,
            target_type=target_type,
            target_id=target_id,
            occurred_at=occurred_at,
            delivery_channels=delivery_channels,
            dedupe_key=dedupe_key,
        )
        response = await self._run(
            lambda: self._client.table("notifications").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_notifications(self, user_id: str, limit: int = 50, unread_only: bool = False) -> List[Dict[str, Any]]:
        def _query():
            query = (
                self._client.table("notifications")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
                .limit(limit)
            )
            if unread_only:
                query = query.eq("read", False)
            return query.execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_unread_notification_count(self, user_id: str) -> int:
        response = await self._run(
            lambda: self._client.table("notifications")
            .select("id", count="exact")
            .eq("user_id", user_id)
            .eq("read", False)
            .execute()
        )
        count = getattr(response, "count", None)
        return int(count or 0)

    async def mark_notification_read(self, notification_id: str, user_id: str) -> bool:
        payload = {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}
        response = await self._run(
            lambda: self._client.table("notifications")
            .update(payload)
            .eq("id", notification_id)
            .eq("user_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return len(data) > 0

    async def mark_all_notifications_read(self, user_id: str) -> int:
        payload = {"read": True, "read_at": datetime.now(timezone.utc).isoformat()}
        response = await self._run(
            lambda: self._client.table("notifications")
            .update(payload)
            .eq("user_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return len(data)

    async def get_notification_preferences(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("notification_preferences")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def upsert_notification_preferences(self, user_id: str, preferences: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(preferences)
        payload["user_id"] = user_id
        payload["updated_at"] = datetime.now(timezone.utc).isoformat()
        response = await self._run(
            lambda: self._client.table("notification_preferences")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return self._first_row(response) or payload

    # Comments & kudos
    async def create_comment(
        self,
        user_id: str,
        target_type: str,
        target_id: str,
        content: str,
        parent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "target_type": target_type,
            "target_id": target_id,
            "content": content,
            "parent_id": parent_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("comments").insert(payload).execute()
        )
        created = self._first_row(response) or payload
        user = next(iter(await self.get_users_by_ids([user_id])), None)
        return self._comment_to_response(created, user)

    async def get_comments(self, target_type: str, target_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("comments")
            .select(self._COMMENT_SELECTION)
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .eq("moderation_state", "visible")
            .order("created_at")
            .execute()
        )
        data = getattr(response, "data", None) or []
        comments = [dict(row) for row in data]
        user_ids = [str(row.get("user_id")) for row in comments if row.get("user_id")]
        users = await self.get_users_by_ids(user_ids)
        users_by_id = {str(user.get("id")): user for user in users if user.get("id")}
        return [
            self._comment_to_response(comment, users_by_id.get(str(comment.get("user_id"))))
            for comment in comments
        ]

    async def get_comment(self, comment_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("comments")
            .select(self._COMMENT_SELECTION)
            .eq("id", comment_id)
            .limit(1)
            .execute()
        )
        comment = self._first_row(response)
        if not comment:
            return None
        user_id = str(comment.get("user_id"))
        user = next(iter(await self.get_users_by_ids([user_id])), None) if user_id else None
        return self._comment_to_response(comment, user)

    async def update_comment(self, comment_id: str, user_id: str, content: str) -> Optional[Dict[str, Any]]:
        updated_at = datetime.now(timezone.utc).isoformat()
        response = await self._run(
            lambda: self._client.table("comments")
            .update({"content": content, "updated_at": updated_at})
            .eq("id", comment_id)
            .eq("user_id", user_id)
            .execute()
        )
        updated = self._first_row(response)
        if not updated:
            return None
        user = next(iter(await self.get_users_by_ids([user_id])), None)
        return self._comment_to_response(updated, user)

    async def delete_comment(self, comment_id: str, user_id: str) -> bool:
        response = await self._run(
            lambda: self._client.table("comments")
            .delete()
            .eq("id", comment_id)
            .eq("user_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return len(data) > 0

    async def create_kudos(self, user_id: str, target_type: str, target_id: str) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "target_type": target_type,
            "target_id": target_id,
        }
        response = await self._run(
            lambda: self._client.table("kudos").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_kudos(self, user_id: str, target_type: str, target_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("kudos")
            .select("*")
            .eq("user_id", user_id)
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def delete_kudos(self, user_id: str, target_type: str, target_id: str) -> bool:
        response = await self._run(
            lambda: self._client.table("kudos")
            .delete()
            .eq("user_id", user_id)
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return len(data) > 0

    async def create_social_report(
        self,
        reporter_id: str,
        target_type: str,
        target_id: str,
        reason: str,
        details: Optional[str] = None,
        moderation_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        existing_response = await self._run(
            lambda: self._client.table("social_reports")
            .select("*")
            .eq("reporter_id", reporter_id)
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .in_("status", ["open", "reviewing"])
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        existing = self._first_row(existing_response)
        if existing:
            return self._social_report_to_response(existing)

        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "contract_version": MODERATION_CONTRACT_VERSION,
            "reporter_id": reporter_id,
            "target_type": target_type,
            "target_id": target_id,
            "reason": reason,
            "details": details,
            "status": "open",
            "moderation_metadata": moderation_metadata or {},
            "created_at": now,
            "updated_at": now,
        }
        response = await self._run(
            lambda: self._client.table("social_reports").insert(payload).execute()
        )
        return self._social_report_to_response(self._first_row(response) or payload)

    async def _moderation_actions_for_reports(self, report_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        unique_ids = [str(report_id) for report_id in dict.fromkeys(report_ids) if report_id]
        if not unique_ids:
            return {}
        try:
            response = await self._run(
                lambda: self._client.table("moderation_actions")
                .select("*")
                .in_("report_id", unique_ids)
                .order("created_at", desc=True)
                .execute()
            )
        except Exception:
            logger.warning("moderation_actions unavailable while listing reports", exc_info=True)
            return {}
        grouped: Dict[str, List[Dict[str, Any]]] = {report_id: [] for report_id in unique_ids}
        for row in getattr(response, "data", None) or []:
            report_id = str(row.get("report_id"))
            grouped.setdefault(report_id, []).append(dict(row))
        return grouped

    async def get_report_summaries(
        self,
        target_type: str,
        target_ids: List[str],
        reporter_id: str,
    ) -> Dict[str, Dict[str, Any]]:
        unique_ids = [str(target_id) for target_id in dict.fromkeys(target_ids) if target_id]
        summaries = {
            target_id: {"viewerReported": False, "reportStatus": None, "reportId": None}
            for target_id in unique_ids
        }
        if not unique_ids:
            return summaries

        response = await self._run(
            lambda: self._client.table("social_reports")
            .select("id, target_id, status")
            .eq("reporter_id", reporter_id)
            .eq("target_type", target_type)
            .in_("target_id", unique_ids)
            .order("created_at", desc=True)
            .execute()
        )
        for row in getattr(response, "data", None) or []:
            target_id = str(row.get("target_id"))
            if target_id in summaries and not summaries[target_id]["viewerReported"]:
                summaries[target_id] = {
                    "viewerReported": True,
                    "reportStatus": row.get("status"),
                    "reportId": row.get("id"),
                }
        return summaries

    async def list_social_reports(
        self,
        status: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        def _query():
            query = window(
                self._client.table("social_reports")
                .select("*")
                .order("created_at", desc=True),
                offset,
                limit,
            )
            if status:
                query = query.eq("status", status)
            return query.execute()

        response = await self._run(_query)
        rows = [dict(row) for row in getattr(response, "data", None) or []]
        actions_by_report = await self._moderation_actions_for_reports([str(row.get("id")) for row in rows])
        for row in rows:
            row["action_history"] = actions_by_report.get(str(row.get("id")), [])
        return [self._social_report_to_response(row) for row in rows]

    async def _apply_moderation_visibility_action(
        self,
        *,
        target_type: str,
        target_id: str,
        action: str,
        reviewer_id: str,
        report_id: str,
        resolution_note: Optional[str],
    ) -> str:
        if action not in {"hide", "remove"}:
            return action_application_status(normalize_resolution_action(action, "resolved"))

        moderation_state = "hidden" if action == "hide" else "removed"
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "moderation_state": moderation_state,
            "moderated_at": now,
            "moderated_by": reviewer_id,
            "moderation_report_id": report_id,
            "moderation_reason": resolution_note,
        }
        try:
            if target_type == "ride":
                response = await self._run(
                    lambda: self._client.table("rides")
                    .update({
                        **payload,
                        "visibility": "private",
                        "comments_enabled": False,
                    })
                    .eq("id", target_id)
                    .execute()
                )
                self._client.table("activities").update({
                    "is_public": False,
                    "visibility": "private",
                    "moderation_state": moderation_state,
                }).eq("target_type", "ride").eq("target_id", target_id).execute()
            elif target_type == "comment":
                response = await self._run(
                    lambda: self._client.table("comments")
                    .update(payload)
                    .eq("id", target_id)
                    .execute()
                )
                self._client.table("activities").update({
                    "is_public": False,
                    "visibility": "private",
                    "moderation_state": moderation_state,
                }).eq("target_type", "comment").eq("target_id", target_id).execute()
            elif target_type == "user":
                response = await self._run(
                    lambda: self._client.table("users")
                    .update({**payload, "is_public": False})
                    .eq("id", target_id)
                    .execute()
                )
                self._client.table("rides").update({
                    **payload,
                    "visibility": "private",
                    "comments_enabled": False,
                }).eq("user_id", target_id).execute()
                self._client.table("comments").update(payload).eq("user_id", target_id).execute()
                self._client.table("activities").update({
                    "is_public": False,
                    "visibility": "private",
                    "moderation_state": moderation_state,
                }).eq("user_id", target_id).execute()
            elif target_type == "ride_media":
                response = await self._run(
                    lambda: self._client.table("ride_media")
                    .update(payload)
                    .eq("id", target_id)
                    .execute()
                )
            else:
                return "unsupported"
        except Exception:
            logger.warning(
                "Failed to apply moderation visibility action target=%s:%s action=%s",
                target_type,
                target_id,
                action,
                exc_info=True,
            )
            return "failed"

        data = getattr(response, "data", None)
        if data == []:
            return "failed"
        return "applied"

    async def resolve_social_report(
        self,
        report_id: str,
        reviewer_id: str,
        status: str,
        resolution_note: Optional[str] = None,
        resolution_action: Optional[str] = None,
        reporter_message: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing_response = await self._run(
            lambda: self._client.table("social_reports")
            .select("*")
            .eq("id", report_id)
            .limit(1)
            .execute()
        )
        existing = self._first_row(existing_response)
        if not existing:
            return None

        now = datetime.now(timezone.utc).isoformat()
        action = normalize_resolution_action(resolution_action, status)
        target_type = str(existing.get("target_type") or "")
        target_id = str(existing.get("target_id") or "")
        action_status = action_application_status(action)
        if status == "resolved":
            action_status = await self._apply_moderation_visibility_action(
                target_type=target_type,
                target_id=target_id,
                action=action.value,
                reviewer_id=reviewer_id,
                report_id=report_id,
                resolution_note=resolution_note,
            )
            if action_status == "failed":
                raise ValueError("Moderation action failed; report remains unresolved")
        reporter_outcome = reporter_outcome_for(status, action)
        payload = {
            "contract_version": MODERATION_CONTRACT_VERSION,
            "status": status,
            "reviewed_by": reviewer_id,
            "reviewed_at": now,
            "updated_at": now,
            "resolution_note": resolution_note,
            "resolution_action": action.value,
            "reporter_outcome": reporter_outcome,
            "reporter_message": reporter_message or reporter_message_for(status, action),
        }
        response = await self._run(
            lambda: self._client.table("social_reports")
            .update(payload)
            .eq("id", report_id)
            .execute()
        )
        row = self._first_row(response)
        if not row:
            return None

        action_payload = {
            "report_id": report_id,
            "actor_id": reviewer_id,
            "action_type": action.value,
            "action_status": action_status,
            "target_type": target_type,
            "target_id": target_id,
            "note": resolution_note,
            "metadata": {
                "status": status,
                "reporter_outcome": reporter_outcome,
                "moderation_state": "hidden" if action.value == "hide" else "removed" if action.value == "remove" else None,
            },
            "created_at": now,
        }
        try:
            action_response = await self._run(
                lambda: self._client.table("moderation_actions").insert(action_payload).execute()
            )
            row["action_history"] = [
                dict(action_row)
                for action_row in (getattr(action_response, "data", None) or [action_payload])
            ]
        except Exception:
            logger.warning("Failed to insert moderation action history", exc_info=True)
            row["action_history"] = []
        return self._social_report_to_response(row)

    async def list_user_social_reports(
        self,
        reporter_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: window(
                self._client.table("social_reports")
                .select("*")
                .eq("reporter_id", reporter_id)
                .order("created_at", desc=True),
                offset,
                limit,
            ).execute()
        )
        return [
            self._social_report_to_reporter_response(dict(row))
            for row in getattr(response, "data", None) or []
        ]

    async def get_social_report_for_reporter(
        self,
        report_id: str,
        reporter_id: str,
    ) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("social_reports")
            .select("*")
            .eq("id", report_id)
            .eq("reporter_id", reporter_id)
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return self._social_report_to_reporter_response(row) if row else None

    async def increment_kudos_count(self, target_type: str, target_id: str) -> None:
        activity = await self._run(
            lambda: self._client.table("activities")
            .select("id, kudos_count")
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .limit(1)
            .execute()
        )
        row = self._first_row(activity)
        if not row:
            return
        new_count = int(row.get("kudos_count") or 0) + 1
        await self._run(
            lambda: self._client.table("activities")
            .update({"kudos_count": new_count})
            .eq("id", row["id"])
            .execute()
        )

    async def get_interaction_summaries(
        self,
        target_type: str,
        target_ids: List[str],
        viewer_user_id: Optional[str] = None,
    ) -> Dict[str, Dict[str, Any]]:
        unique_ids = [str(target_id) for target_id in dict.fromkeys(target_ids) if target_id]
        summaries = {
            target_id: {
                "kudosCount": 0,
                "commentCount": 0,
                "viewerHasKudos": False,
                "viewerReported": False,
                "reportStatus": None,
            }
            for target_id in unique_ids
        }
        if not unique_ids:
            return summaries

        comments_response = await self._run(
            lambda: self._client.table("comments")
            .select("target_id")
            .eq("target_type", target_type)
            .in_("target_id", unique_ids)
            .eq("moderation_state", "visible")
            .execute()
        )
        for row in getattr(comments_response, "data", None) or []:
            target_id = str(row.get("target_id"))
            if target_id in summaries:
                summaries[target_id]["commentCount"] += 1

        kudos_response = await self._run(
            lambda: self._client.table("kudos")
            .select("target_id, user_id")
            .eq("target_type", target_type)
            .in_("target_id", unique_ids)
            .execute()
        )
        for row in getattr(kudos_response, "data", None) or []:
            target_id = str(row.get("target_id"))
            if target_id in summaries:
                summaries[target_id]["kudosCount"] += 1
                if viewer_user_id and str(row.get("user_id")) == viewer_user_id:
                    summaries[target_id]["viewerHasKudos"] = True

        if viewer_user_id:
            report_summaries = await self.get_report_summaries(target_type, unique_ids, viewer_user_id)
            for target_id, report_summary in report_summaries.items():
                if target_id in summaries:
                    summaries[target_id].update({
                        "viewerReported": report_summary.get("viewerReported", False),
                        "reportStatus": report_summary.get("reportStatus"),
                    })

        return summaries

    async def decrement_kudos_count(self, target_type: str, target_id: str) -> None:
        activity = await self._run(
            lambda: self._client.table("activities")
            .select("id, kudos_count")
            .eq("target_type", target_type)
            .eq("target_id", target_id)
            .limit(1)
            .execute()
        )
        row = self._first_row(activity)
        if not row:
            return
        new_count = max(int(row.get("kudos_count") or 0) - 1, 0)
        await self._run(
            lambda: self._client.table("activities")
            .update({"kudos_count": new_count})
            .eq("id", row["id"])
            .execute()
        )

    async def get_user_rides_for_date(self, user_id: str, ride_date: date) -> List[Dict[str, Any]]:
        start_dt = datetime.combine(ride_date, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = start_dt + timedelta(days=1)
        response = await self._run(
            lambda: self._client.table("rides")
            .select("id, tss, duration_sec, distance_m")
            .eq("user_id", str(user_id))
            .eq("processing_status", "completed")
            .gte("started_at", start_dt.isoformat())
            .lt("started_at", end_dt.isoformat())
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def create_proof(
        self,
        ride_id: str,
        effort_score: float,
        signature: str = "",
        user_id: Optional[str] = None,
        proof_id: Optional[str] = None,
        dung_amount: Optional[float] = None,
        proof_hash: Optional[str] = None,
        status: Optional[str] = None,
    ) -> str:
        proof_id = proof_id or str(uuid.uuid4())
        payload = {
            "id": proof_id,
            "ride_id": ride_id,
            "effort_score": float(effort_score),
            "signature": signature,
            "user_id": user_id,
            "dung_amount": dung_amount,
            "proof_hash": proof_hash,
            "status": status,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Remove None values to avoid insert errors on missing columns
        payload = {k: v for k, v in payload.items() if v is not None}
        await self._run(lambda: self._client.table("proofs").insert(payload).execute())
        return proof_id

    async def get_proof(self, proof_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("proofs")
            .select("*")
            .eq("id", proof_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_proof_for_ride(self, ride_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("proofs")
            .select("*")
            .eq("ride_id", ride_id)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def proof_has_mint(self, proof_id: str) -> bool:
        response = await self._run(
            lambda: self._client.table("mint_events")
            .select("id")
            .eq("proof_id", proof_id)
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return bool(row)

    async def update_proof_status(self, proof_id: str, status: str, tx_signature: Optional[str]) -> None:
        proof = await self.get_proof(proof_id)
        update_data: Dict[str, Any] = {"status": status}
        if tx_signature:
            update_data["signature"] = tx_signature
        await self._run(
            lambda: self._client.table("proofs")
            .update(update_data)
            .eq("id", proof_id)
            .execute()
        )
        if not proof:
            return
        user_id = proof.get("user_id")
        ride_id = proof.get("ride_id")
        if not user_id and ride_id:
            ride = await self.get_ride(str(ride_id))
            user_id = (ride or {}).get("user_id")
        if not user_id:
            return
        try:
            await self.create_notification(
                user_id=str(user_id),
                notification_type="proof_updated",
                title="Proof updated",
                message=f"Your ride proof is now {status}.",
                data={
                    "proof_id": proof_id,
                    "ride_id": ride_id,
                    "status": status,
                    "tx_signature": tx_signature,
                },
                target_type="proof",
                target_id=proof_id,
                dedupe_key=f"proof_updated:{proof_id}:{status}:{tx_signature or ''}",
            )
        except Exception:
            logger.warning("Failed to emit proof_updated notification", exc_info=True)

    async def create_mint_event(
        self,
        proof_id: str,
        amount: float,
        tx_hash: str,
        status: str,
        created_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        event_id = str(uuid.uuid4())
        created = (created_at or datetime.now(timezone.utc)).isoformat()
        payload = {
            "id": event_id,
            "proof_id": proof_id,
            "amount": float(amount),
            "tx_hash": tx_hash,
            "status": status,
            "created_at": created,
        }
        await self._run(
            lambda: self._client.table("mint_events").insert(payload).execute()
        )
        return payload

    async def record_mint_event(
        self,
        user_id: str,
        ride_id: str,
        proof_id: str,
        dung_amount: float,
        tx_signature: Optional[str],
        status: str,
    ) -> Dict[str, Any]:
        payload = {
            "proof_id": proof_id,
            "amount": float(dung_amount),
            "tx_hash": tx_signature or "",
            "status": status,
            "user_id": user_id,
            "ride_id": ride_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        # Insert using existing table; ignore missing columns by stripping None
        payload = {k: v for k, v in payload.items() if v is not None}
        await self._run(lambda: self._client.table("mint_events").insert(payload).execute())
        return payload

    async def health(self) -> bool:
        try:
            await self._run(
                lambda: self._client.table("users").select("id").limit(1).execute()
            )
            return True
        except Exception as exc:  # pragma: no cover - defensive logging
            logger.exception("Supabase health check failed: %s", exc)
            return False

    async def get_token_balances(self, user_id: str) -> Dict[str, Any]:
        total_kcal = 0.0
        rides_response = await self._run(
            lambda: self._client.table("rides")
            .select("kcals")
            .eq("user_id", user_id)
            .execute()
        )
        rides_data = getattr(rides_response, "data", None) or []
        for row in rides_data:
            try:
                total_kcal += float(row.get("kcals") or 0)
            except (TypeError, ValueError):
                continue

        proofs_response = await self._run(
            lambda: self._client.table("proofs")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        proofs_data = getattr(proofs_response, "data", None) or []
        proof_ids = [row.get("id") for row in proofs_data if row.get("id")]

        total_dung = Decimal(0)
        if proof_ids:
            minted_response = await self._run(
                lambda: self._client.table("mint_events")
                .select("amount, proof_id")
                .in_("proof_id", proof_ids)
                .execute()
            )
            minted_data = getattr(minted_response, "data", None) or []
            for row in minted_data:
                try:
                    amount = Decimal(str(row.get("amount") or 0))
                    if not amount.is_finite():
                        continue
                    total_dung += amount
                except (InvalidOperation, TypeError, ValueError):
                    continue

        return {"dung": total_dung, "kcal": float(total_kcal)}

    async def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("user_state")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def update_cal_balance(self, user_id: str, amount: float) -> Dict[str, Any]:
        state = await self.get_user_state(user_id)
        current_balance = float(state.get("cal_balance") or 0) if state else 0.0
        payload = {
            "user_id": user_id,
            "cal_balance": current_balance + float(amount),
            "cal_earned_today": float(state.get("cal_earned_today") or 0) if state else 0.0,
            "last_cal_mint": state.get("last_cal_mint") if state else None,
            "total_rides": state.get("total_rides") if state else 0,
            "total_tss": state.get("total_tss") if state else 0,
            "bio_score": state.get("bio_score") if state else 1000,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def deduct_cal(self, user_id: str, amount: float) -> None:
        """DEPRECATED: Wrong CAL model. CAL is not deducted from users.

        The correct model: CAL is earned from TSS, tributed to vaults crossed.
        This method is kept for backwards compatibility but should not be called.
        """
        import warnings
        warnings.warn(
            "deduct_cal is deprecated - CAL is earned from TSS, not deducted from users",
            DeprecationWarning,
            stacklevel=2,
        )

    async def refund_cal(self, user_id: str, amount: float) -> None:
        # Refund by incrementing CAL balance; fall back to update_cal_balance if RPC missing.
        await self.update_cal_balance(user_id, float(amount))

    async def update_proof_signature(self, proof_id: str, signature: str) -> None:
        await self._run(
            lambda: self._client.table("proofs")
            .update({"signature": signature})
            .eq("id", proof_id)
            .execute()
        )

    async def update_user_state(self, user_id: str, updates: Dict[str, Any]) -> None:
        updates = dict(updates)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._run(
            lambda: self._client.table("user_state")
            .upsert({**updates, "user_id": user_id}, on_conflict="user_id")
            .execute()
        )

    async def get_segment_by_id(self, segment_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("segments")
            .select("*")
            .eq("id", segment_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def delete_ride(self, ride_id: str) -> None:
        await self._run(
            lambda: self._client.table("rides")
            .delete()
            .eq("id", ride_id)
            .execute()
        )

    async def get_segment_pool(self, segment_id: str) -> Dict[str, float]:
        response = await self._run(
            lambda: self._client.table("claims")
            .select("amount, lp_tokens")
            .eq("segment_id", segment_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        total_dung = sum(float(row.get("amount") or 0) for row in data)
        total_lp = sum(float(row.get("lp_tokens") or 0) for row in data)
        return {"total_dung": total_dung, "total_lp": total_lp}

    async def create_segment_effort(
        self,
        ride_id: uuid.UUID,
        user_id: uuid.UUID,
        segment_id: Union[uuid.UUID, int],
        elapsed_time_sec: int,
        effort_score: float,
        average_power_w: Optional[float],
        average_hr_bpm: Optional[float],
        elevation_gain_m: Optional[float],
        distance_m: Optional[float],
        is_pr: bool,
        is_kom: bool,
        rank_at_time: Optional[int],
    ) -> uuid.UUID:
        effort_id = str(uuid.uuid4())
        payload = {
            "id": effort_id,
            "ride_id": str(ride_id),
            "user_id": str(user_id),
            "segment_id": str(segment_id),
            "elapsed_time_sec": elapsed_time_sec,
            "effort_score": float(effort_score),
            "average_power_w": average_power_w,
            "average_hr_bpm": average_hr_bpm,
            "elevation_gain_m": elevation_gain_m,
            "distance_m": distance_m,
            "is_pr": is_pr,
            "is_kom": is_kom,
            "rank_at_time": rank_at_time,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        await self._run(
            lambda: self._client.table("segment_efforts").insert(payload).execute()
        )
        return uuid.UUID(effort_id)

    async def get_segment_best_effort(self, segment_id: Union[uuid.UUID, int]) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("segment_id", str(segment_id))
            .order("elapsed_time_sec")
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_user_best_segment_effort(self, user_id: uuid.UUID, segment_id: Union[uuid.UUID, int]) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("*")
            .eq("segment_id", str(segment_id))
            .eq("user_id", str(user_id))
            .order("elapsed_time_sec")
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_segment_effort_rank(self, segment_id: Union[uuid.UUID, int], elapsed_time_sec: int) -> Optional[int]:
        response = await self._run(
            lambda: self._client.table("segment_efforts")
            .select("id", count="exact")
            .eq("segment_id", str(segment_id))
            .lt("elapsed_time_sec", elapsed_time_sec)
            .execute()
        )
        count = getattr(response, "count", None)
        if count is None:
            return None
        return int(count) + 1

    async def record_cal_mint(self, user_id: str, amount: float, minted_at: datetime) -> Dict[str, Any]:
        state = await self.get_user_state(user_id)
        cal_balance = float(state.get("cal_balance") or 0) if state else 0.0
        last_mint_raw = state.get("last_cal_mint") if state else None
        cal_earned_today = float(state.get("cal_earned_today") or 0) if state else 0.0

        last_mint_dt: Optional[datetime] = None
        if last_mint_raw:
            try:
                last_mint_dt = datetime.fromisoformat(str(last_mint_raw).replace("Z", "+00:00"))
            except ValueError:
                last_mint_dt = None

        if last_mint_dt and last_mint_dt.date() == minted_at.date():
            cal_earned_today += float(amount)
        else:
            cal_earned_today = float(amount)

        payload = {
            "user_id": user_id,
            "cal_balance": cal_balance + float(amount),
            "cal_earned_today": cal_earned_today,
            "last_cal_mint": minted_at.isoformat(),
            "total_rides": state.get("total_rides") if state else 0,
            "total_tss": state.get("total_tss") if state else 0,
            "bio_score": state.get("bio_score") if state else 1000,
            "updated_at": minted_at.isoformat(),
        }

        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def get_user_ride_streak(self, user_id: str) -> int:
        response = await self._run(
            lambda: self._client.rpc("get_user_ride_streak", {"p_user_id": user_id}).execute()
        )
        data = getattr(response, "data", None)
        if isinstance(data, list) and data:
            try:
                return int(data[0])
            except (TypeError, ValueError):
                return 0
        try:
            return int(data)
        except (TypeError, ValueError):
            return 0

    async def create_vesting_schedule(
        self,
        user_id: str,
        token_type: str,
        total_amount: int,
        end_date: datetime,
        source_type: Optional[str],
        source_id: Optional[str],
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "token_type": token_type,
            "total_amount": total_amount,
            "end_date": end_date.isoformat(),
            "source_type": source_type,
            "source_id": source_id,
        }
        response = await self._run(
            lambda: self._client.table("vesting_schedules").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_vesting_schedules(self, user_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("vesting_schedules")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_user_claims(self, user_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("claims")
            .select(
                "segment_id, amount, lp_tokens, staked_at, last_harvest_epoch, segments(name,length_m,elev_gain_m)"
            )
            .eq("user_id", user_id)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_user_claim(self, user_id: str, segment_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("claims")
            .select("*")
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def upsert_claim(self, user_id: str, segment_id: str, amount: float, lp_tokens: float) -> None:
        payload = {
            "user_id": user_id,
            "segment_id": segment_id,
            "amount": float(amount),
            "lp_tokens": float(lp_tokens),
            "staked_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._run(
            lambda: self._client.table("claims")
            .upsert(payload, on_conflict="user_id,segment_id")
            .execute()
        )

    async def delete_claim(self, user_id: str, segment_id: str) -> None:
        await self._run(
            lambda: self._client.table("claims")
            .delete()
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .execute()
        )

    async def get_current_epoch(self, segment_id: str) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("epochs")
            .select("*")
            .eq("segment_id", segment_id)
            .gt("end_time", datetime.now(timezone.utc).isoformat())
            .order("epoch_number", desc=True)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_epoch(self, segment_id: str, epoch_number: int) -> Optional[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("epochs")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_segment_epoch_activity(self, segment_id: str, epoch_number: int) -> Dict[str, Any]:
        response = await self._run(
            lambda: self._client.table("segment_activity")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .limit(1)
            .execute()
        )
        return self._first_row(response) or {}

    async def update_claim_harvest(self, user_id: str, segment_id: str, last_harvest_epoch: int) -> None:
        payload = {"last_harvest_epoch": last_harvest_epoch}
        await self._run(
            lambda: self._client.table("claims")
            .update(payload)
            .eq("user_id", user_id)
            .eq("segment_id", segment_id)
            .execute()
        )

    async def create_harvest_event(
        self,
        user_id: str,
        segment_id: str,
        epoch_number: int,
        lp_tokens_held: float,
        dung_harvested: float,
        tx_signature: Optional[str] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "segment_id": segment_id,
            "epoch_number": epoch_number,
            "lp_tokens_held": lp_tokens_held,
            "dung_harvested": dung_harvested,
            "tx_signature": tx_signature,
            "harvested_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("harvest_events").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_leaderboard(self, segment_id: str, epoch_number: int, limit: int = 100) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("leaderboard_entries")
            .select("*")
            .eq("segment_id", segment_id)
            .eq("epoch_number", epoch_number)
            .order("rank")
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def create_token_transaction(
        self,
        user_id: str,
        tx_type: str,
        token_type: str,
        amount: float,
        balance_after: Optional[float],
        reference_type: Optional[str],
        reference_id: Optional[str],
        tx_signature: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "tx_type": tx_type,
            "token_type": token_type,
            "amount": amount,
            "balance_after": balance_after,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "tx_signature": tx_signature,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        response = await self._run(
            lambda: self._client.table("token_transactions").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        tx_type: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        query = window(
            self._client.table("token_transactions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True),
            offset,
            limit,
        )
        if tx_type:
            query = query.eq("tx_type", tx_type)
        if token_type:
            query = query.eq("token_type", token_type)
        response = await self._run(lambda: query.execute())
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_all_user_transactions(self, user_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("token_transactions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def create_token_transaction(
        self,
        user_id: str,
        tx_type: str,
        token_type: str,
        amount: float,
        balance_after: Optional[float],
        reference_type: Optional[str],
        reference_id: Optional[str],
        tx_signature: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        payload = {
            "user_id": user_id,
            "tx_type": tx_type,
            "token_type": token_type,
            "amount": amount,
            "balance_after": balance_after,
            "reference_type": reference_type,
            "reference_id": reference_id,
            "tx_signature": tx_signature,
            "metadata": metadata or {},
            "created_at": datetime.now(timezone.utc).isoformat(),
        }

        response = await self._run(
            lambda: self._client.table("token_transactions").insert(payload).execute()
        )
        return self._first_row(response) or payload

    async def get_user_transactions(
        self,
        user_id: str,
        limit: int = 50,
        offset: int = 0,
        tx_type: Optional[str] = None,
        token_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        def _query():
            query = (
                self._client.table("token_transactions")
                .select("*")
                .eq("user_id", user_id)
                .order("created_at", desc=True)
            )
            if tx_type:
                query = query.eq("tx_type", tx_type)
            if token_type:
                query = query.eq("token_type", token_type)
            return window(query, offset, limit).execute()

        response = await self._run(_query)
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def get_all_user_transactions(self, user_id: str) -> List[Dict[str, Any]]:
        response = await self._run(
            lambda: self._client.table("token_transactions")
            .select("*")
            .eq("user_id", user_id)
            .order("created_at", desc=True)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def _run(self, func: Any, operation: str = "supabase") -> Any:
        from .metrics import (
            SUPABASE_REQUEST_DURATION,
            SUPABASE_REQUEST_ERRORS,
            SUPABASE_REQUESTS_IN_FLIGHT,
        )

        start = time.perf_counter()
        SUPABASE_REQUESTS_IN_FLIGHT.inc()
        try:
            return await asyncio.to_thread(func)
        except Exception:
            SUPABASE_REQUEST_ERRORS.labels(operation=operation).inc()
            raise
        finally:
            SUPABASE_REQUESTS_IN_FLIGHT.dec()
            SUPABASE_REQUEST_DURATION.labels(operation=operation).observe(
                time.perf_counter() - start
            )

    async def _fetch_user_by_wallet(self, wallet: str, include_created: bool = False) -> Optional[Dict[str, Any]]:
        selection = "id, wallet, email"
        if include_created:
            selection += ", created_at"
        response = await self._run(
            lambda: self._client.table("users")
            .select(selection)
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    @staticmethod
    def _first_row(response: Any) -> Optional[Dict[str, Any]]:
        data = getattr(response, "data", None)
        if isinstance(data, dict):
            return data
        if data:
            return data[0]
        return None

    @staticmethod
    def _coerce_date_value(value: Any) -> Any:
        if isinstance(value, date):
            return value
        if isinstance(value, datetime):
            return value.date()
        if isinstance(value, str):
            try:
                return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
            except ValueError:
                try:
                    return date.fromisoformat(value)
                except ValueError:
                    return value
        return value

    def _with_date_field(self, row: Optional[Dict[str, Any]], field: str = "date") -> Optional[Dict[str, Any]]:
        if not row:
            return None
        copy_row = dict(row)
        copy_row[field] = self._coerce_date_value(copy_row.get(field))
        return copy_row

    # Profile Hub implementations

    async def check_username_available(self, username: str) -> tuple[bool, Optional[str]]:
        """Check if username is available and valid"""
        import re

        # Validate format
        if not re.match(r"^[a-z0-9_]{3,20}$", username.lower()):
            return False, "Username must be 3-20 characters, lowercase letters, numbers, and underscores only"

        # Check reserved usernames
        reserved = {"admin", "support", "help", "api", "www", "mail", "root", "system", "mod", "moderator"}
        if username.lower() in reserved:
            return False, "This username is reserved"

        # Check if taken
        response = await self._run(
            lambda: self._client.table("users")
            .select("id")
            .eq("username", username.lower())
            .limit(1)
            .execute()
        )
        if self._first_row(response):
            return False, "Username is already taken"

        return True, None

    async def update_user_profile(self, wallet: str, updates: Dict[str, Any]) -> Dict[str, Any]:
        """Update user profile fields"""
        forbidden = {"ftp_w", "ftpW", "ftp_w_source", "ftpWSource"}.intersection(updates)
        if forbidden:
            raise ValueError("Manual FTP is not a profile field")
        # Clean up updates - only include non-None values
        clean_updates = {k: v for k, v in updates.items() if v is not None}
        clean_updates["updated_at"] = datetime.now(timezone.utc).isoformat()

        # Normalize username to lowercase
        if "username" in clean_updates:
            clean_updates["username"] = clean_updates["username"].lower()

        response = await self._run(
            lambda: self._client.table("users")
            .update(clean_updates)
            .eq("wallet", wallet)
            .execute()
        )
        for row in getattr(response, "data", None) or []:
            if row.get("id"):
                clear_user_row_cache(str(row["id"]))

        # Return updated profile
        return await self.get_full_user_profile(wallet) or {}

    async def get_user_by_identifier(self, identifier: str) -> Optional[Dict[str, Any]]:
        """Get user by user ID, wallet address, or username."""
        try:
            user_uuid = str(uuid.UUID(identifier))
        except (TypeError, ValueError):
            user_uuid = None

        if user_uuid:
            row = await self.get_user_by_id(user_uuid)
            if row:
                return row

        # Try wallet first (base58 format)
        if len(identifier) >= 32:
            response = await self._run(
                lambda: self._client.table("users")
                .select("*")
                .eq("wallet", identifier)
                .limit(1)
                .execute()
            )
            row = self._first_row(response)
            if row:
                return row

        # Try username
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .eq("username", identifier.lower())
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get aggregated ride stats for user"""
        # Get ride stats
        response = await self._run(
            lambda: self._client.table("rides")
                .select(
                    "tss, economic_tss, kcals, duration_sec, distance_m, elevation_gain_m"
                )
            .eq("user_id", user_id)
            .execute()
        )
        rides = getattr(response, "data", None) or []

        total_rides = len(rides)
        total_tss = sum(float(r.get("tss") or 0) for r in rides)
        total_economic_tss = sum(
            float(
                r.get("economic_tss")
                if r.get("economic_tss") is not None
                else (r.get("tss") or 0)
            )
            for r in rides
        )
        total_kcals = sum(float(r.get("kcals") or 0) for r in rides)
        total_duration = sum(int(r.get("duration_sec") or 0) for r in rides)
        total_distance_m = sum(float(r.get("distance_m") or 0) for r in rides)
        total_elevation_m = sum(float(r.get("elevation_gain_m") or 0) for r in rides)

        # Get DUNG earned
        proofs_response = await self._run(
            lambda: self._client.table("proofs")
            .select("id")
            .eq("user_id", user_id)
            .execute()
        )
        proof_ids = [p["id"] for p in (getattr(proofs_response, "data", None) or [])]

        total_dung = 0
        if proof_ids:
            mints_response = await self._run(
                lambda: self._client.table("mint_events")
                .select("amount")
                .in_("proof_id", proof_ids)
                .execute()
            )
            total_dung = sum(int(m.get("amount") or 0) for m in (getattr(mints_response, "data", None) or []))

        return {
            "total_rides": total_rides,
            "total_distance_km": total_distance_m / 1000.0,
            "total_elevation_m": total_elevation_m,
            "total_tss": total_tss,
            "total_economic_tss": total_economic_tss,
            "total_kcals": total_kcals,
            "total_duration_sec": total_duration,
            "total_dung_earned": total_dung,
        }

    async def get_user_max_power(self, user_id: uuid.UUID) -> Optional[float]:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("max_power_w")
            .eq("user_id", str(user_id))
            .order("max_power_w", desc=True, nullsfirst=False)
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        if row and row.get("max_power_w") is not None:
            return float(row["max_power_w"])
        return None

    async def get_user_total_distance(self, user_id: uuid.UUID) -> float:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("distance_m")
            .eq("user_id", str(user_id))
            .execute()
        )
        rides = getattr(response, "data", None) or []
        return sum(float(r.get("distance_m") or 0) for r in rides) / 1000.0  # km

    async def get_user_total_elevation(self, user_id: uuid.UUID) -> float:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("elevation_gain_m")
            .eq("user_id", str(user_id))
            .execute()
        )
        rides = getattr(response, "data", None) or []
        return sum(float(r.get("elevation_gain_m") or 0) for r in rides)

    async def get_user_ride_count(self, user_id: uuid.UUID) -> int:
        response = await self._run(
            lambda: self._client.table("rides")
            .select("id", count="exact")
            .eq("user_id", str(user_id))
            .execute()
        )
        count = getattr(response, "count", None)
        return int(count or 0)

    async def get_user_riding_streak(self, user_id: uuid.UUID) -> int:
        """
        Calculate consecutive day streak based on completed rides.
        """
        response = await self._run(
            lambda: self._client.table("rides")
            .select("completed_at, started_at")
            .eq("user_id", str(user_id))
            .order("completed_at", desc=True)
            .limit(60)
            .execute()
        )
        rides = getattr(response, "data", None) or []
        if not rides:
            return 0

        streak = 0
        today = datetime.now(timezone.utc).date()

        for idx, ride in enumerate(rides):
            ts_raw = ride.get("completed_at") or ride.get("started_at")
            if not ts_raw:
                continue
            try:
                ride_date = datetime.fromisoformat(str(ts_raw).replace("Z", "+00:00")).date()
            except ValueError:
                continue

            if idx == 0:
                if (today - ride_date).days > 1:
                    break

            if idx == 0:
                expected = today
            else:
                expected = today - timedelta(days=streak)

            if ride_date == expected or ride_date == expected - timedelta(days=1):
                streak += 1
                today = ride_date
            else:
                break

        return streak

    async def get_user_wallet(self, user_id: uuid.UUID) -> Optional[str]:
        response = await self._run(
            lambda: self._client.table("users")
            .select("wallet")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return row.get("wallet") if row else None

    async def get_full_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get full user profile including stats"""
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        user = self._first_row(response)
        if not user:
            return None
        user.pop("ftp_w", None)
        user.pop("ftp_w_source", None)

        # Get stats
        stats = await self.get_user_stats(user["id"])

        return {**user, **stats}

    # CAL airdrop implementations
    async def get_users_due_for_airdrop(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get users whose next_cal_airdrop is in the past (due for airdrop)"""
        now = datetime.now(timezone.utc)
        response = await self._run(
            lambda: self._client.table("user_state")
            .select("user_id, cal_balance, next_cal_airdrop")
            .lte("next_cal_airdrop", now.isoformat())
            .limit(limit)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return [dict(row) for row in data]

    async def process_cal_airdrop(self, user_id: str, amount: float) -> Dict[str, Any]:
        """Add CAL to user and schedule next airdrop in 24 hours"""
        now = datetime.now(timezone.utc)
        next_airdrop = now + timedelta(hours=24)

        state = await self.get_user_state(user_id)
        cal_balance = float(state.get("cal_balance") or 0) if state else 0.0

        payload = {
            "user_id": user_id,
            "cal_balance": cal_balance + float(amount),
            "cal_earned_today": float(amount),
            "last_cal_mint": now.isoformat(),
            "next_cal_airdrop": next_airdrop.isoformat(),
            "updated_at": now.isoformat(),
        }

        # Preserve other fields
        if state:
            payload["total_rides"] = state.get("total_rides", 0)
            payload["total_tss"] = state.get("total_tss", 0)
            payload["bio_score"] = state.get("bio_score", 1000)

        await self._run(
            lambda: self._client.table("user_state")
            .upsert(payload, on_conflict="user_id")
            .execute()
        )
        return payload

    async def add_to_waitlist(self, email: str, source: str, ip_hash: int) -> Dict[str, Any]:
        """Add an email to the waitlist table."""
        now = datetime.now(timezone.utc)
        payload = {
            "id": str(uuid.uuid4()),
            "email": email.lower().strip(),
            "source": source,
            "ip_hash": ip_hash,
            "created_at": now.isoformat(),
        }

        # Use upsert to avoid duplicates (email is unique constraint)
        await self._run(
            lambda: self._client.table("waitlist")
            .upsert(payload, on_conflict="email")
            .execute()
        )
        return payload

    async def get_patterns_for_activity(
        self,
        activity_id: uuid.UUID,
    ) -> Dict[str, Any]:
        """Get all patterns for an activity."""
        climb_response = await self._run(
            lambda: self._client.table("patterns_climb")
            .select("*")
            .eq("activity_id", str(activity_id))
            .execute()
        )
        steady_response = await self._run(
            lambda: self._client.table("patterns_steady")
            .select("*")
            .eq("activity_id", str(activity_id))
            .limit(1)
            .execute()
        )
        exploration_response = await self._run(
            lambda: self._client.table("patterns_exploration")
            .select("*")
            .eq("activity_id", str(activity_id))
            .limit(1)
            .execute()
        )

        climb_data = getattr(climb_response, "data", None) or []
        steady_data = getattr(steady_response, "data", None) or []
        exploration_data = getattr(exploration_response, "data", None) or []

        return {
            "climb_patterns": climb_data,
            "steady_pattern": steady_data[0] if steady_data else None,
            "exploration_pattern": exploration_data[0] if exploration_data else None,
        }

    async def get_wallet_tile_history(
        self,
        wallet: str,
    ) -> set:
        """Get all tile IDs previously visited by a wallet."""
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id")
            .eq("wallet", wallet)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return {row["tile_id"] for row in data}

    async def get_global_tile_coverage(self) -> set:
        """Get all tile IDs ever visited by any wallet."""
        # This could be expensive - consider caching or materialized view
        response = await self._run(
            lambda: self._client.table("wallet_tile_history")
            .select("tile_id")
            .execute()
        )
        data = getattr(response, "data", None) or []
        return {row["tile_id"] for row in data}


@lru_cache(maxsize=1)
def _build_supabase_client() -> BackendSupabaseClient:
    settings = load_supabase_settings()
    if not settings:
        raise RuntimeError("Supabase configuration is missing. Ensure SUPABASE_URL and service key are set.")
    # Increase timeout from default 5s to 60s to handle large batch inserts
    # Long rides (7+ hours) can have 18,000+ GPS points
    options = ClientOptions(postgrest_client_timeout=60)
    return create_backend_supabase_client(
        settings.url,
        settings.service_key,
        options=options,
    )


def create_supabase_repository() -> SupabaseRepository:
    client = _build_supabase_client()
    return SupabaseRepository(client)


def get_supabase_client() -> BackendSupabaseClient:
    """Get the shared Supabase client instance."""
    return _build_supabase_client()
