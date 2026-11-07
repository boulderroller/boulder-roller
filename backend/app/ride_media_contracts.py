"""Helpers for turning ride_media rows into client-safe media contracts."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from .schemas import RideMedia
from .services.file_storage import FileStorageService, create_file_storage_service

logger = logging.getLogger(__name__)

RIDE_MEDIA_SIGNED_URL_EXPIRY_SECONDS = 3600


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


async def serialize_ride_media(
    row: dict[str, Any],
    *,
    storage: Optional[FileStorageService] = None,
    signed_url_expiry_seconds: int = RIDE_MEDIA_SIGNED_URL_EXPIRY_SECONDS,
) -> RideMedia:
    """Serialize a ride_media row and attach a fresh signed image URL."""
    storage_service = storage or create_file_storage_service()
    url: Optional[str] = None
    storage_path = row.get("storage_path")
    if row.get("upload_status") == "ready" and isinstance(storage_path, str) and storage_path:
        try:
            url = await storage_service.get_signed_url(
                storage_path,
                expires_in=signed_url_expiry_seconds,
            )
        except Exception as exc:
            logger.warning(
                "[RideMedia] Failed to sign media %s error_type=%s",
                row.get("id"),
                type(exc).__name__,
            )

    return RideMedia(
        id=UUID(str(row.get("id"))),
        ride_id=UUID(str(row.get("ride_id"))),
        url=url,
        file_name=row.get("file_name"),
        mime_type=str(row.get("mime_type") or "image/jpeg"),
        size_bytes=int(row.get("size_bytes") or 0),
        width=int(row["width"]) if row.get("width") is not None else None,
        height=int(row["height"]) if row.get("height") is not None else None,
        sort_order=int(row.get("sort_order") or 0),
        role=row.get("role") if row.get("role") in {"photo", "cover"} else "photo",
        moderation_state=str(row.get("moderation_state") or "visible"),
        created_at=_parse_datetime(row.get("created_at")),
    )


async def serialize_ride_media_list(
    rows: list[dict[str, Any]],
    *,
    storage: Optional[FileStorageService] = None,
) -> list[RideMedia]:
    """Serialize a list of media rows using one storage client."""
    if not rows:
        return []
    storage_service = storage or create_file_storage_service()
    semaphore = asyncio.Semaphore(12)

    async def _serialize(row: dict[str, Any]) -> RideMedia:
        async with semaphore:
            return await serialize_ride_media(row, storage=storage_service)

    return list(await asyncio.gather(*(_serialize(row) for row in rows)))
