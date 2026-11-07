import asyncio
import time
from typing import Any, Dict, Optional
from uuid import UUID

from supabase import Client

from ..repositories import _build_supabase_client


class EmergencyControls:
    """Service for managing emergency system controls."""

    def __init__(self, client: Optional[Client] = None) -> None:
        self._client = client or _build_supabase_client()
        self._cache: Dict[str, Any] = {}
        self._cache_ttl = 10  # seconds
        self._last_refresh = 0.0
        self._lock = asyncio.Lock()

    async def _run(self, func):
        return await asyncio.to_thread(func)

    async def _refresh_cache(self) -> None:
        """Refresh the controls cache from database."""
        now = time.time()
        if now - self._last_refresh < self._cache_ttl:
            return

        async with self._lock:
            if now - self._last_refresh < self._cache_ttl:
                return

            result = await self._run(lambda: self._client.table("system_controls").select("key,value").execute())
            rows = getattr(result, "data", None) or []
            self._cache = {row["key"]: row.get("value", {}) for row in rows}
            self._last_refresh = time.time()

    async def is_enabled(self, control: str) -> bool:
        """Check if a control is enabled."""
        await self._refresh_cache()
        value = self._cache.get(control, {"enabled": True})
        return bool(value.get("enabled", True))

    async def get_reason(self, control: str) -> Optional[str]:
        """Get the reason for a disabled control."""
        await self._refresh_cache()
        value = self._cache.get(control, {})
        return value.get("reason")

    async def set_control(
        self,
        control: str,
        enabled: bool,
        reason: Optional[str] = None,
        admin_id: Optional[UUID] = None,
    ) -> None:
        """Set a control value."""
        from datetime import datetime, timezone

        value = {"enabled": enabled, "reason": reason}
        if control == "maintenance_mode":
            value["message"] = reason

        payload = {
            "key": control,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "updated_by": str(admin_id) if admin_id else None,
        }
        await self._run(lambda: self._client.table("system_controls").upsert(payload).execute())
        self._last_refresh = 0.0

    async def check_staking(self) -> tuple[bool, Optional[str]]:
        enabled = await self.is_enabled("staking_enabled")
        reason = await self.get_reason("staking_enabled") if not enabled else None
        return enabled, reason

    async def check_minting(self) -> tuple[bool, Optional[str]]:
        enabled = await self.is_enabled("minting_enabled")
        reason = await self.get_reason("minting_enabled") if not enabled else None
        return enabled, reason

    async def check_uploads(self) -> tuple[bool, Optional[str]]:
        enabled = await self.is_enabled("uploads_enabled")
        reason = await self.get_reason("uploads_enabled") if not enabled else None
        return enabled, reason

    async def check_maintenance(self) -> tuple[bool, Optional[str]]:
        await self._refresh_cache()
        value = self._cache.get("maintenance_mode", {"enabled": False})
        message = value.get("message") or value.get("reason")
        return bool(value.get("enabled", False)), message


async def get_emergency_controls() -> EmergencyControls:
    return EmergencyControls()
