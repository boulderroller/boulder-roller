"""Auth repository - nonces, refresh tokens, and session management."""
from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .base import BaseRepository

logger = logging.getLogger(__name__)


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


class AuthRepository(BaseRepository):
    """Repository for authentication and session management."""

    def _first_row(self, response) -> Optional[Dict[str, Any]]:
        """Extract first row from response."""
        data = getattr(response, "data", None) or []
        return dict(data[0]) if data else None

    @staticmethod
    def _is_legacy_device_uniqueness_conflict(exc: Exception) -> bool:
        """Detect envs that still enforce the pre-history unique device index."""
        message = str(exc)
        return "idx_auth_refresh_unique_device" in message or (
            "auth_refresh_tokens" in message
            and "wallet, device_id" in message
            and "duplicate key value" in message
        )

    # === Nonce Management ===

    async def save_nonce(
        self,
        wallet: str,
        nonce: str,
        issued_at: datetime,
        expires_at: datetime,
        device_id: str,
    ) -> Dict[str, Any]:
        """Save a nonce through the database-owned deleted-wallet fence."""
        nonce_id = str(uuid.uuid4())
        try:
            response = await self._run(
                lambda: self._client.rpc(
                    "br_issue_auth_nonce",
                    {
                        "p_nonce_id": nonce_id,
                        "p_wallet": wallet,
                        "p_nonce": nonce,
                        "p_issued_at": issued_at.isoformat(),
                        "p_expires_at": expires_at.isoformat(),
                        "p_device_id": device_id,
                    },
                ).execute()
            )
        except Exception as exc:
            if not _is_missing_rpc_error(exc, "br_issue_auth_nonce"):
                raise
            # Code may deploy shortly before migration 152. Preserve the old
            # deleted-wallet check, then use the legacy insert. If 152 is
            # actually installed and only PostgREST's cache is stale, its raw
            # write trigger rejects this path and the error remains fail-closed.
            deleted_response = await self._run(
                lambda: self._client.table("deleted_wallets")
                .select("wallet")
                .eq("wallet", wallet)
                .limit(1)
                .execute()
            )
            if self._first_row(deleted_response) is not None:
                raise RuntimeError("account_deleted") from exc
            response = await self._run(
                lambda: self._client.table("auth_nonces").insert(
                    {
                        "id": nonce_id,
                        "wallet": wallet,
                        "nonce": nonce,
                        "issued_at": issued_at.isoformat(),
                        "expires_at": expires_at.isoformat(),
                        "device_id": device_id,
                    }
                ).execute()
            )
        row = self._first_row(response)
        if row is None:
            raise RuntimeError("Nonce authority returned no nonce")
        return row

    async def get_nonce(self, nonce: str) -> Optional[Dict[str, Any]]:
        """Get a nonce by its value."""
        response = await self._run(
            lambda: self._client.table("auth_nonces")
            .select("*")
            .eq("nonce", nonce)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def mark_nonce_used(self, nonce_id: uuid.UUID) -> None:
        """Mark a nonce as used."""
        response = await self._run(
            lambda: self._client.table("auth_nonces")
            .select("wallet")
            .eq("id", str(nonce_id))
            .limit(1)
            .execute()
        )
        row = self._first_row(response)
        if row and row.get("wallet"):
            await self.consume_nonce(nonce_id, str(row["wallet"]))

    async def consume_nonce(self, nonce_id: uuid.UUID, wallet: str) -> bool:
        """Atomically mark an unused nonce as used.

        Returns False when another verifier already consumed the nonce.
        """
        used_at = datetime.now(timezone.utc).isoformat()
        try:
            response = await self._run(
                lambda: self._client.rpc(
                    "br_consume_auth_nonce",
                    {
                        "p_nonce_id": str(nonce_id),
                        "p_wallet": wallet,
                        "p_used_at": used_at,
                    },
                ).execute()
            )
        except Exception as exc:
            if not _is_missing_rpc_error(exc, "br_consume_auth_nonce"):
                raise
            deleted_response = await self._run(
                lambda: self._client.table("deleted_wallets")
                .select("wallet")
                .eq("wallet", wallet)
                .limit(1)
                .execute()
            )
            if self._first_row(deleted_response) is not None:
                raise RuntimeError("account_deleted") from exc
            response = await self._run(
                lambda: self._client.table("auth_nonces")
                .update({"used_at": used_at})
                .eq("id", str(nonce_id))
                .eq("wallet", wallet)
                .is_("used_at", "null")
                .execute()
            )
            return bool(getattr(response, "data", None))
        data = getattr(response, "data", None) or []
        return bool(data and data[0].get("consumed"))

    # === Refresh Token Management ===

    async def delete_refresh_tokens_for_device(
        self, wallet: str, device_id: str
    ) -> None:
        """Compatibility wrapper: revoke, never delete, device refresh-token history."""
        await self.revoke_active_refresh_tokens_for_device(
            wallet=wallet,
            device_id=device_id,
            revoked_at=datetime.now(timezone.utc),
            reason="replaced",
        )

    async def revoke_active_refresh_tokens_for_device(
        self,
        wallet: str,
        device_id: str,
        revoked_at: datetime,
        reason: str,
    ) -> None:
        """Revoke active refresh tokens for a wallet+device without deleting history."""
        await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .update({
                "revoked_at": revoked_at.isoformat(),
                "revocation_reason": reason,
            })
            .eq("wallet", wallet)
            .eq("device_id", device_id)
            .is_("revoked_at", "null")
            .execute()
        )

    async def store_refresh_token(
        self,
        wallet: str,
        device_id: str,
        token_hash: str,
        expires_at: datetime,
        user_agent: Optional[str],
        revoke_existing: bool = True,
    ) -> None:
        """Store a new refresh token after revoking any active token for the device."""
        if revoke_existing:
            await self.revoke_active_refresh_tokens_for_device(
                wallet=wallet,
                device_id=device_id,
                revoked_at=datetime.now(timezone.utc),
                reason="replaced",
            )
        payload = {
            "wallet": wallet,
            "device_id": device_id,
            "token_hash": token_hash,
            "user_agent": user_agent,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "expires_at": expires_at.isoformat(),
        }
        try:
            await self._run(
                lambda: self._client.table("auth_refresh_tokens").insert(payload).execute()
            )
        except Exception as exc:
            if not self._is_legacy_device_uniqueness_conflict(exc):
                raise

            logger.error(
                "auth_refresh_tokens still enforces legacy device uniqueness; "
                "falling back to in-place session row replacement. Apply "
                "backend/supabase/migrations/20260421_104_auth_refresh_token_history.sql "
                "or the matching backend/sql migration to restore token history."
            )
            await self._run(
                lambda: self._client.table("auth_refresh_tokens")
                .update({
                    **payload,
                    "revoked_at": None,
                    "revocation_reason": None,
                })
                .eq("wallet", wallet)
                .eq("device_id", device_id)
                .execute()
            )

    async def get_refresh_token(self, token_hash: str) -> Optional[Dict[str, Any]]:
        """Get a refresh token by its hash."""
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("*")
            .eq("token_hash", token_hash)
            .limit(1)
            .execute()
        )
        return self._first_row(response)

    async def revoke_refresh_token(
        self, token_hash: str, revoked_at: datetime, reason: str = "revoked"
    ) -> None:
        """Revoke a refresh token."""
        await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .update({
                "revoked_at": revoked_at.isoformat(),
                "revocation_reason": reason,
            })
            .eq("token_hash", token_hash)
            .execute()
        )

    async def rotate_refresh_token(
        self,
        *,
        old_token_hash: str,
        new_token_hash: str,
        wallet: str,
        device_id: str,
        expires_at: datetime,
        user_agent: Optional[str],
        rotated_at: datetime,
    ) -> bool:
        """Conditionally revoke one active refresh token and store its replacement."""
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .update({
                "revoked_at": rotated_at.isoformat(),
                "revocation_reason": "rotated",
            })
            .eq("token_hash", old_token_hash)
            .eq("wallet", wallet)
            .eq("device_id", device_id)
            .is_("revoked_at", "null")
            .execute()
        )
        data = getattr(response, "data", None) or []
        if not data:
            return False

        await self.store_refresh_token(
            wallet=wallet,
            device_id=device_id,
            token_hash=new_token_hash,
            expires_at=expires_at,
            user_agent=user_agent,
            revoke_existing=False,
        )
        return True

    # === Identity Linking (wallet <-> Privy subject) ===

    @staticmethod
    def _normalize_identity_subject(provider: str, provider_subject: str) -> str:
        if provider == "wallet":
            return provider_subject.strip()
        return provider_subject.strip()

    @staticmethod
    def _is_missing_auth_identities_table_error(exc: Exception) -> bool:
        message = str(exc)
        return "PGRST205" in message and "public.auth_identities" in message

    async def get_identity_user_id(
        self,
        provider: str,
        provider_subject: str,
    ) -> Optional[str]:
        """Resolve a canonical user ID by external identity."""
        subject = self._normalize_identity_subject(provider, provider_subject)
        try:
            response = await self._run(
                lambda: self._client.table("auth_identities")
                .select("user_id")
                .eq("provider", provider)
                .eq("provider_subject", subject)
                .limit(1)
                .execute()
            )
        except Exception as exc:
            if self._is_missing_auth_identities_table_error(exc):
                logger.warning(
                    "auth_identities table missing; identity lookup fallback active (provider=%s)",
                    provider,
                )
                return None
            raise
        row = self._first_row(response)
        return str(row.get("user_id")) if row and row.get("user_id") else None

    async def link_wallet_identity(
        self,
        user_id: str,
        wallet: str,
    ) -> None:
        """Link wallet identity to user with deterministic conflict checks."""
        subject = self._normalize_identity_subject("wallet", wallet)
        existing_user_id = await self.get_identity_user_id("wallet", subject)
        if existing_user_id and existing_user_id != user_id:
            raise ValueError("wallet identity already linked to another user")

        payload = {
            "user_id": user_id,
            "provider": "wallet",
            "provider_subject": subject,
            "wallet": wallet,
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._run(
                lambda: self._client.table("auth_identities")
                .upsert(payload, on_conflict="provider,provider_subject")
                .execute()
            )
        except Exception as exc:
            if self._is_missing_auth_identities_table_error(exc):
                logger.warning(
                    "auth_identities table missing; skipping wallet identity link (wallet=%s)",
                    "[redacted]",
                )
                return
            raise

    async def link_privy_identity(
        self,
        user_id: str,
        privy_subject: str,
        wallet: Optional[str] = None,
        metadata: Optional[dict[str, Any]] = None,
    ) -> None:
        """Link Privy subject identity to user with deterministic conflict checks."""
        subject = self._normalize_identity_subject("privy", privy_subject)
        existing_user_id = await self.get_identity_user_id("privy", subject)
        if existing_user_id and existing_user_id != user_id:
            raise ValueError("privy identity already linked to another user")

        payload = {
            "user_id": user_id,
            "provider": "privy",
            "provider_subject": subject,
            "wallet": wallet,
            "metadata": metadata or {},
            "last_seen_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            await self._run(
                lambda: self._client.table("auth_identities")
                .upsert(payload, on_conflict="provider,provider_subject")
                .execute()
            )
        except Exception as exc:
            if self._is_missing_auth_identities_table_error(exc):
                logger.warning("auth_identities table missing; skipping privy identity link")
                return
            raise

    # === Session Management ===

    async def list_user_sessions(
        self,
        wallet: str,
        current_token_hash: Optional[str],
        current_device_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all active sessions for a user."""
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id, device_id, user_agent, created_at, last_used_at, token_hash")
            .eq("wallet", wallet)
            .is_("revoked_at", "null")
            .gt("expires_at", datetime.now(timezone.utc).isoformat())
            .order("last_used_at", desc=True, nullsfirst=False)
            .execute()
        )
        sessions = getattr(response, "data", None) or []

        result = []
        for s in sessions:
            session_dict = dict(s)
            token_hash = session_dict.get("token_hash")
            session_dict["is_current"] = bool(
                (
                    current_token_hash
                    and token_hash in {
                        current_token_hash,
                        current_token_hash[:16],
                    }
                )
                or (
                    not current_token_hash
                    and current_device_id
                    and session_dict.get("device_id") == current_device_id
                )
            )
            result.append(session_dict)

        return result

    async def revoke_session(self, session_id: str, wallet: str) -> bool:
        """Revoke a specific session."""
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .update({
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revocation_reason": "revoked",
            })
            .eq("id", session_id)
            .eq("wallet", wallet)
            .execute()
        )
        data = getattr(response, "data", None)
        return bool(data)

    async def revoke_all_other_sessions(
        self, wallet: str, current_token_hash: str, reason: str = "revoked"
    ) -> int:
        """Revoke all sessions except the current one."""
        # First get count of sessions to revoke
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id")
            .eq("wallet", wallet)
            .neq("token_hash", current_token_hash)
            .is_("revoked_at", "null")
            .execute()
        )
        sessions = getattr(response, "data", None) or []
        count = len(sessions)

        if count > 0:
            await self._run(
                lambda: self._client.table("auth_refresh_tokens")
                .update({
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "revocation_reason": reason,
                })
                .eq("wallet", wallet)
                .neq("token_hash", current_token_hash)
                .is_("revoked_at", "null")
                .execute()
            )

        return count

    async def revoke_all_sessions(
        self,
        wallet: str,
        include_current: bool,
        current_token_hash: str,
        reason: str = "revoked",
    ) -> int:
        """Revoke all sessions, optionally including the current one.

        Args:
            wallet: The user's wallet address
            include_current: If True, revoke all sessions including current
            current_token_hash: Hash of the current session's token

        Returns:
            Number of sessions revoked
        """
        if not include_current:
            return await self.revoke_all_other_sessions(wallet, current_token_hash, reason=reason)

        # Revoke ALL sessions including current
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id")
            .eq("wallet", wallet)
            .is_("revoked_at", "null")
            .execute()
        )
        sessions = getattr(response, "data", None) or []
        count = len(sessions)

        if count > 0:
            await self._run(
                lambda: self._client.table("auth_refresh_tokens")
                .update({
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "revocation_reason": reason,
                })
                .eq("wallet", wallet)
                .is_("revoked_at", "null")
                .execute()
            )

        return count

    # === Device Tracking ===

    async def is_device_known(self, wallet: str, device_id: str) -> bool:
        """
        Check if a device has been used before for this wallet.

        A device is "known" if there's any historical record of a refresh token
        being issued for this wallet+device_id combination, regardless of
        whether that token is currently active.

        Returns:
            True if device has been seen before, False if it's new
        """
        # Check auth_refresh_tokens for any record (including revoked/expired)
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id")
            .eq("wallet", wallet)
            .eq("device_id", device_id)
            .limit(1)
            .execute()
        )
        data = getattr(response, "data", None) or []
        return len(data) > 0

    async def revoke_session_with_reason(
        self,
        session_id: str,
        wallet: str,
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """
        Revoke a session and record the reason.

        Args:
            session_id: ID of the session to revoke
            wallet: Wallet address (for ownership verification)
            reason: Revocation reason (logged_out_other_device, password_changed,
                   admin_action, session_expired)

        Returns:
            The revoked session data or None if not found
        """
        # First get the session to return its data
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id, device_id, user_agent, wallet")
            .eq("id", session_id)
            .eq("wallet", wallet)
            .limit(1)
            .execute()
        )

        data = getattr(response, "data", None) or []
        if not data:
            return None
        session_data = dict(data[0])

        # Revoke the session with reason
        await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .update({
                "revoked_at": datetime.now(timezone.utc).isoformat(),
                "revocation_reason": reason,
            })
            .eq("id", session_id)
            .eq("wallet", wallet)
            .execute()
        )

        session_data["revocation_reason"] = reason
        return session_data

    async def revoke_all_other_sessions_with_reason(
        self,
        wallet: str,
        current_token_hash: str,
        reason: str,
    ) -> List[Dict[str, Any]]:
        """
        Revoke all sessions except the current one and record the reason.

        Returns:
            List of revoked session data (id, device_id, etc.)
        """
        # Get sessions to revoke
        response = await self._run(
            lambda: self._client.table("auth_refresh_tokens")
            .select("id, device_id, user_agent, wallet")
            .eq("wallet", wallet)
            .neq("token_hash", current_token_hash)
            .is_("revoked_at", "null")
            .execute()
        )
        sessions = [dict(s) for s in (getattr(response, "data", None) or [])]

        if sessions:
            # Revoke all of them with reason
            await self._run(
                lambda: self._client.table("auth_refresh_tokens")
                .update({
                    "revoked_at": datetime.now(timezone.utc).isoformat(),
                    "revocation_reason": reason,
                })
                .eq("wallet", wallet)
                .neq("token_hash", current_token_hash)
                .is_("revoked_at", "null")
                .execute()
            )

            # Add reason to returned data
            for session in sessions:
                session["revocation_reason"] = reason

        return sessions
