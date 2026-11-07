"""User repository - user accounts, profiles, and stats."""
from __future__ import annotations

from ..services.privacy_logging import scrub_log_text
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from .base import BaseRepository

_logger = logging.getLogger(__name__)


def _text_array_literal(values: list[str]) -> str:
    """PostgREST filters use PostgreSQL array syntax, not Python list repr."""
    return "{" + ",".join('"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"' for value in values) + "}"


def _is_transient_auth_authority_error(exc: Exception) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in (
            "connection refused",
            "connection reset",
            "connection attempts failed",
            "database unavailable",
            "server disconnected",
            "service unavailable",
            "temporarily unavailable",
            "timed out",
            "timeout",
            "502",
            "503",
            "504",
        )
    )


def _is_missing_rpc_error(exc: Exception, function_name: str) -> bool:
    message = str(exc).lower()
    return function_name.lower() in message and any(
        marker in message
        for marker in (
            "does not exist",
            "schema cache",
            "could not find",
            "pgrst202",
        )
    )


class UserRepository(BaseRepository):
    """Repository for user account and profile operations."""

    _PRIVATE_PROFILE_SELECTION = (
        "id, wallet, username, display_name, bio, avatar_url, avatar_storage_path, "
        "avatar_mime_type, avatar_size_bytes, avatar_updated_at, avatar_cleanup_storage_paths, "
        "avatar_pending_upload_id, avatar_pending_storage_path, avatar_pending_file_name, "
        "avatar_pending_mime_type, avatar_pending_size_bytes, avatar_pending_created_at, "
        "email, weight_kg, weight_kg_source, "
        "preferred_units, is_public, "
        "default_ride_visibility, created_at, theme_id, is_dark_mode, rider_type, location"
    )

    # Physiology fields where an explicit null is a meaningful write (clear),
    # not an omission — see boulderroller-v2-coq7q.
    _CLEARABLE_PROFILE_FIELDS = ("weight_kg",)

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    async def _fetch_user_row_by_wallet(
        self,
        wallet: str,
        selection: str,
    ) -> Optional[Dict[str, Any]]:
        """Internal helper to fetch a user row by wallet with a custom selection."""
        response = await self._run(
            lambda: self._client.table("users")
            .select(selection)
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def _fetch_user_by_wallet(
        self, wallet: str, include_created: bool = False
    ) -> Optional[Dict[str, Any]]:
        """Internal helper to fetch user record by wallet."""
        selection = "id, wallet, email"
        if include_created:
            selection += ", created_at"
        return await self._fetch_user_row_by_wallet(wallet, selection)

    async def get_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        """Get minimal user state by normalized email address."""
        normalized = email.strip().lower()
        if not normalized:
            return None
        response = await self._run(
            lambda: self._client.table("users")
            .select("id, wallet, email")
            .eq("email", normalized)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def create_user(self, wallet: str, email: Optional[str] = None) -> str:
        """Atomically create or resolve an active, non-tombstoned user."""
        normalized_email = email.strip().lower() if email else None
        candidate_user_id = str(uuid.uuid4())
        try:
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
        except Exception as exc:
            if not _is_missing_rpc_error(exc, "br_get_or_create_active_user"):
                raise
            _logger.warning(
                "[UserRepository] active-user RPC unavailable; using the "
                "legacy tombstone-checked create path for %s",
                "[redacted]",
            )
            return await self._create_user_before_lifecycle_migration(
                wallet=wallet,
                normalized_email=normalized_email,
                candidate_user_id=candidate_user_id,
            )
        row = self._first_row(response)
        if not row or not row.get("user_id"):
            raise RuntimeError("Active user authority returned no user")
        if bool(row.get("was_created")):
            from ..metrics import KPI_USERS_CREATED

            KPI_USERS_CREATED.inc()
        return str(row["user_id"])

    async def _create_user_before_lifecycle_migration(
        self,
        *,
        wallet: str,
        normalized_email: Optional[str],
        candidate_user_id: str,
    ) -> str:
        """Compatibility path used only while migration 152's RPC is absent."""
        deleted_response = await self._run(
            lambda: self._client.table("deleted_wallets")
            .select("wallet")
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )
        if self._first_row(deleted_response) is not None:
            raise RuntimeError("account_deleted")

        existing = await self._fetch_user_by_wallet(wallet)
        if existing:
            user_id = str(existing["id"])
            if normalized_email and existing.get("email") != normalized_email:
                await self._run(
                    lambda: self._client.table("users")
                    .update({"email": normalized_email})
                    .eq("id", user_id)
                    .execute()
                )
            return user_id

        payload = {
            "id": candidate_user_id,
            "wallet": wallet,
            "email": normalized_email or "",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await self._run(lambda: self._client.table("users").insert(payload).execute())
        from ..metrics import KPI_USERS_CREATED

        KPI_USERS_CREATED.inc()
        return candidate_user_id

    async def get_user_id(self, wallet: str) -> Optional[str]:
        """Get user ID by wallet address."""
        record = await self._fetch_user_by_wallet(wallet)
        if not record:
            return None
        return record.get("id")

    async def get_auth_account_authority(self, wallet: str) -> Dict[str, Optional[str]]:
        """Read tombstone precedence and identity through one database authority.

        Migration 152's RPC is wallet-fenced and makes legacy/new tombstones
        win even if an interrupted legacy deletion left a users row behind.
        A bounded transient retry fails closed. The multi-read compatibility
        branch is used only while the new RPC is genuinely absent.
        """
        try:
            return await self._get_auth_account_authority_rpc(wallet)
        except Exception as exc:
            if _is_missing_rpc_error(exc, "br_get_auth_account_authority"):
                return await self._get_auth_account_authority_before_migration(wallet)
            if not _is_transient_auth_authority_error(exc):
                raise
            _logger.warning(
                "[UserRepository] transient auth authority RPC failed for %s; "
                "retrying once: %s",
                "[redacted]",
                scrub_log_text(exc),
            )
        try:
            return await self._get_auth_account_authority_rpc(wallet)
        except Exception as exc:
            if _is_missing_rpc_error(exc, "br_get_auth_account_authority"):
                return await self._get_auth_account_authority_before_migration(wallet)
            raise

    async def _get_auth_account_authority_rpc(
        self,
        wallet: str,
    ) -> Dict[str, Optional[str]]:
        response = await self._run(
            lambda: self._client.rpc(
                "br_get_auth_account_authority",
                {"p_wallet": wallet},
            ).execute()
        )
        row = self._first_row(response)
        if row is None:
            raise RuntimeError("Auth account authority returned no row")
        raw_user_id = row.get("user_id")
        raw_state = row.get("account_state")
        user_id = str(raw_user_id) if raw_user_id else None
        account_state = str(raw_state) if raw_state is not None else None
        if account_state is None:
            if user_id is not None:
                raise RuntimeError("Auth account authority returned an invalid identity")
            return {"user_id": None, "account_state": None}
        if account_state not in {"active", "deletion_pending", "anonymized"}:
            raise RuntimeError("Auth account authority returned an invalid lifecycle state")
        if account_state in {"active", "deletion_pending"} and user_id is None:
            raise RuntimeError("Auth account authority returned an invalid identity")
        return {
            "user_id": None if account_state == "anonymized" else user_id,
            "account_state": account_state,
        }

    async def _get_auth_account_authority_before_migration(
        self,
        wallet: str,
    ) -> Dict[str, Optional[str]]:
        """Fail-safe compatibility for a code-first deploy before migration 152."""
        deleted: Optional[bool] = None
        for attempt in range(2):
            try:
                deleted = await self.is_wallet_deleted(wallet)
                break
            except Exception as exc:
                if _is_missing_rpc_error(exc, "br_is_account_deleted"):
                    break
                if attempt == 0 and _is_transient_auth_authority_error(exc):
                    _logger.warning(
                        "[UserRepository] transient legacy tombstone authority failed "
                        "for %s; retrying once: %s",
                        "[redacted]",
                        scrub_log_text(exc),
                    )
                    continue
                raise
        if deleted is None:
            response = await self._run(
                lambda: self._client.table("deleted_wallets")
                .select("wallet")
                .eq("wallet", wallet)
                .limit(1)
                .execute()
            )
            deleted = self._first_row(response) is not None
        if deleted:
            return {"user_id": None, "account_state": "anonymized"}

        try:
            row = await self._fetch_user_row_by_wallet(wallet, "id,account_state")
        except Exception as exc:
            message = str(exc).lower()
            lifecycle_column_missing = "account_state" in message and any(
                marker in message
                for marker in (
                    "does not exist",
                    "schema cache",
                    "could not find",
                    "pgrst204",
                )
            )
            if not lifecycle_column_missing:
                raise
            row = await self._fetch_user_row_by_wallet(wallet, "id")
            return {
                "user_id": str(row["id"]) if row and row.get("id") else None,
                "account_state": "active" if row and row.get("id") else None,
            }
        if row is None:
            return {"user_id": None, "account_state": None}
        account_state = str(row.get("account_state") or "")
        if account_state not in {"active", "deletion_pending", "anonymized"}:
            raise RuntimeError("User account has an invalid lifecycle state")
        return {
            "user_id": None if account_state == "anonymized" else str(row["id"]),
            "account_state": account_state,
        }

    async def is_wallet_deleted(self, wallet: str) -> bool:
        """Return the database-authoritative account-deletion tombstone state."""
        response = await self._run(
            lambda: self._client.rpc(
                "br_is_account_deleted",
                {"p_wallet": wallet},
            ).execute()
        )
        data = getattr(response, "data", None)
        if isinstance(data, bool):
            return data
        if isinstance(data, list) and len(data) == 1 and isinstance(data[0], bool):
            return data[0]
        raise RuntimeError("Deleted-account authority returned a malformed response")

    async def get_account_state(self, wallet: str) -> Optional[str]:
        """Return the lifecycle state used by the central authentication gate."""
        row = await self._fetch_user_row_by_wallet(wallet, "account_state")
        if row is None:
            return None
        account_state = str(row.get("account_state") or "")
        if account_state not in {"active", "deletion_pending", "anonymized"}:
            raise RuntimeError("User account has an invalid lifecycle state")
        return account_state

    async def get_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get the minimal profile used before ride processing is admitted."""
        return await self._fetch_user_row_by_wallet(
            wallet,
            "id, wallet, email, created_at, weight_kg",
        )

    async def get_profile_setup_state(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get the minimal profile state needed for onboarding/bootstrap checks."""
        try:
            return await self._fetch_user_row_by_wallet(
                wallet,
                "id, username, profile_setup_completed_at",
            )
        except Exception as exc:
            if "profile_setup_completed_at" not in str(exc):
                raise
            _logger.warning(
                "[UserRepository] users.profile_setup_completed_at unavailable; "
                "falling back to legacy setup state for %s",
                "[redacted]",
            )
            return await self._fetch_user_row_by_wallet(wallet, "id, username")

    async def get_private_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get private profile fields without expensive aggregated stats."""
        return await self._fetch_user_row_by_wallet(wallet, self._PRIVATE_PROFILE_SELECTION)

    async def get_public_user_identity(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get public identity fields for rider-facing attribution."""
        return await self._fetch_user_row_by_wallet(
            wallet,
            "id, wallet, username, display_name, avatar_url, avatar_storage_path, "
            "avatar_mime_type, avatar_size_bytes, avatar_updated_at, is_public",
        )

    async def get_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user by ID."""
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .eq("id", user_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def get_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """Get multiple users by their IDs in a single query."""
        if not user_ids:
            return []
        response = await self._run(
            lambda: self._client.table("users")
            .select("*")
            .in_("id", user_ids)
            .execute()
        )
        return getattr(response, "data", None) or []

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

    async def check_username_available(self, username: str) -> tuple[bool, Optional[str]]:
        """Check if username is available and valid."""
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
        """Update user profile fields.

        ``None`` values are dropped (partial-update semantics) except for the
        clearable physiology fields, where an explicitly provided null means
        "clear this" and must persist. Setting or clearing a physiology value
        keeps its provenance column in lockstep: manual on write, NULL on
        clear. (boulderroller-v2-coq7q)
        """
        forbidden = {"ftp_w", "ftpW", "ftp_w_source", "ftpWSource"}.intersection(updates)
        if forbidden:
            raise ValueError("Manual FTP is not a profile field")
        clean_updates = {
            k: v
            for k, v in updates.items()
            if v is not None or k in self._CLEARABLE_PROFILE_FIELDS
        }
        for field in self._CLEARABLE_PROFILE_FIELDS:
            if field in clean_updates:
                clean_updates[f"{field}_source"] = (
                    "manual" if clean_updates[field] is not None else None
                )
        now = datetime.now(timezone.utc).isoformat()
        clean_updates["updated_at"] = now

        # Normalize username to lowercase
        if "username" in clean_updates:
            clean_updates["username"] = clean_updates["username"].lower()
            if clean_updates["username"]:
                setup_state = await self.get_profile_setup_state(wallet)
                if setup_state is None or (
                    "profile_setup_completed_at" in setup_state
                    and not setup_state.get("profile_setup_completed_at")
                ):
                    clean_updates["profile_setup_completed_at"] = now

        await self._run(
            lambda: self._client.table("users")
            .update(clean_updates)
            .eq("wallet", wallet)
            .execute()
        )

        return await self.get_private_user_profile(wallet) or {}

    async def begin_avatar_upload(
        self,
        *,
        user_id: str,
        upload_id: str,
        storage_path: str,
        file_name: Optional[str],
        mime_type: str,
        size_bytes: int,
    ) -> Dict[str, Any]:
        """Record a pending rider avatar upload without changing the active avatar."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "avatar_pending_upload_id": upload_id,
            "avatar_pending_storage_path": storage_path,
            "avatar_pending_file_name": file_name,
            "avatar_pending_mime_type": mime_type,
            "avatar_pending_size_bytes": int(size_bytes),
            "avatar_pending_created_at": now,
            "updated_at": now,
        }
        response = await self._run(
            lambda: self._client.table("users")
            .update(payload)
            .eq("id", user_id)
            .execute()
        )
        return self._first_row(response) or payload

    async def complete_avatar_upload(
        self,
        *,
        user_id: str,
        upload_id: str,
        storage_path: str,
        size_bytes: Optional[int] = None,
        mime_type: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Promote the pending avatar upload to the active public avatar."""
        profile = await self.get_user_by_id(user_id)
        if not profile or profile.get("avatar_pending_upload_id") != upload_id:
            return {}
        if storage_path != "sanitized/" + str(profile.get("avatar_pending_storage_path")):
            return {}

        now = datetime.now(timezone.utc).isoformat()
        cleanup_paths = list(profile.get("avatar_cleanup_storage_paths") or [])
        old_path = profile.get("avatar_storage_path")
        if old_path and old_path != storage_path and old_path not in cleanup_paths:
            cleanup_paths.append(old_path)
        payload = {
            "avatar_url": None,
            "avatar_storage_path": storage_path,
            "avatar_mime_type": mime_type or profile.get("avatar_pending_mime_type"),
            "avatar_size_bytes": int(size_bytes or profile.get("avatar_pending_size_bytes") or 0),
            "avatar_updated_at": now,
            "avatar_cleanup_storage_paths": cleanup_paths,
            "avatar_pending_upload_id": None,
            "avatar_pending_storage_path": None,
            "avatar_pending_file_name": None,
            "avatar_pending_mime_type": None,
            "avatar_pending_size_bytes": None,
            "avatar_pending_created_at": None,
            "updated_at": now,
        }
        response = await self._run(
            lambda: self._client.table("users")
            .update(payload)
            .eq("id", user_id)
            .eq("avatar_pending_upload_id", upload_id)
            .execute()
        )
        return self._first_row(response) or {}

    async def finish_avatar_cleanup(self, user_id: str, paths: list[str]) -> bool:
        """Clear only the cleanup references whose deletion was verified."""
        response = await self._run(
            lambda: self._client.table("users")
            .update({"avatar_cleanup_storage_paths": []})
            .eq("id", user_id)
            .eq("avatar_cleanup_storage_paths", _text_array_literal(paths))
            .execute()
        )
        return bool(self._first_row(response))

    async def delete_avatar(self, user_id: str, *, expected_profile: Dict[str, Any]) -> Dict[str, Any]:
        """Remove active and pending avatar metadata from the profile row."""
        now = datetime.now(timezone.utc).isoformat()
        payload = {
            "avatar_url": None,
            "avatar_storage_path": None,
            "avatar_mime_type": None,
            "avatar_size_bytes": None,
            "avatar_updated_at": None,
            "avatar_cleanup_storage_paths": [],
            "avatar_pending_upload_id": None,
            "avatar_pending_storage_path": None,
            "avatar_pending_file_name": None,
            "avatar_pending_mime_type": None,
            "avatar_pending_size_bytes": None,
            "avatar_pending_created_at": None,
            "updated_at": now,
        }
        def clear_if_unchanged():
            query = self._client.table("users").update(payload).eq("id", user_id)
            for key in ("avatar_storage_path", "avatar_pending_upload_id", "avatar_pending_storage_path"):
                value = expected_profile.get(key)
                query = query.is_(key, "null") if value is None else query.eq(key, value)
            return query.eq("avatar_cleanup_storage_paths", _text_array_literal(expected_profile.get("avatar_cleanup_storage_paths") or [])).execute()
        response = await self._run(clear_if_unchanged)
        return self._first_row(response) or {}

    async def get_full_user_profile(self, wallet: str) -> Optional[Dict[str, Any]]:
        """Get full user profile including stats."""
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

        stats = await self.get_user_stats(user["id"])
        return {**user, **stats}

    async def get_user_stats(self, user_id: str) -> Dict[str, Any]:
        """Get aggregated ride stats for user."""
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

    async def get_user_state(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Get user state (CAL balance, etc.)."""
        response = await self._run(
            lambda: self._client.table("user_state")
            .select("*")
            .eq("user_id", user_id)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def update_user_state(self, user_id: str, updates: Dict[str, Any]) -> None:
        """Update user state fields."""
        updates = dict(updates)
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        await self._run(
            lambda: self._client.table("user_state")
            .upsert({**updates, "user_id": user_id}, on_conflict="user_id")
            .execute()
        )

    async def get_user_max_power(self, user_id: uuid.UUID) -> Optional[float]:
        """Get user's maximum power from all rides."""
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
        """Get user's total distance in km."""
        response = await self._run(
            lambda: self._client.table("rides")
            .select("distance_m")
            .eq("user_id", str(user_id))
            .execute()
        )
        rides = getattr(response, "data", None) or []
        return sum(float(r.get("distance_m") or 0) for r in rides) / 1000.0

    async def get_user_total_elevation(self, user_id: uuid.UUID) -> float:
        """Get user's total elevation gain in meters."""
        response = await self._run(
            lambda: self._client.table("rides")
            .select("elevation_gain_m")
            .eq("user_id", str(user_id))
            .execute()
        )
        rides = getattr(response, "data", None) or []
        return sum(float(r.get("elevation_gain_m") or 0) for r in rides)

    async def get_user_ride_count(self, user_id: uuid.UUID) -> int:
        """Get total number of rides for user."""
        response = await self._run(
            lambda: self._client.table("rides")
            .select("id", count="exact")
            .eq("user_id", str(user_id))
            .execute()
        )
        count = getattr(response, "count", None)
        return int(count or 0)

    async def get_user_riding_streak(self, user_id: uuid.UUID) -> int:
        """Calculate consecutive day streak based on completed rides."""
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
        """Get wallet address for a user ID."""
        response = await self._run(
            lambda: self._client.table("users")
            .select("wallet")
            .eq("id", str(user_id))
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        return row.get("wallet") if row else None

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

        await self._run(
            lambda: self._client.table("waitlist")
            .upsert(payload, on_conflict="email")
            .execute()
        )
        return payload
