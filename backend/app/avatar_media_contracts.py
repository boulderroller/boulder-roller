"""Helpers for rider avatar storage and public signing.

Avatars are identity media, not ride activity media, so they live on the
users/profile contract instead of the ride_media table. The public contract
still exposes avatarUrl, but it is derived from private storage metadata.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from .services.file_storage import FileStorageService, create_file_storage_service

logger = logging.getLogger(__name__)

AVATAR_SIGNED_URL_EXPIRY_SECONDS = 3600
MAX_AVATAR_FILE_SIZE_BYTES = 15 * 1024 * 1024

ALLOWED_AVATAR_MIME_TYPES = {
    "image/jpeg": "jpg",
    "image/jpg": "jpg",
    "image/png": "png",
    "image/webp": "webp",
    "image/heic": "heic",
    "image/heif": "heif",
}


def normalize_avatar_mime_type(value: str) -> str:
    normalized = (value or "").split(";", 1)[0].strip().lower()
    if normalized == "image/jpg":
        return "image/jpeg"
    return normalized


def avatar_extension(mime_type: str, file_name: Optional[str] = None) -> str:
    normalized = normalize_avatar_mime_type(mime_type)
    ext = ALLOWED_AVATAR_MIME_TYPES.get(normalized)
    if ext:
        return ext
    if file_name and "." in file_name:
        candidate = file_name.rsplit(".", 1)[-1].strip().lower()
        if candidate in {"jpg", "jpeg", "png", "webp", "heic", "heif"}:
            return "jpg" if candidate == "jpeg" else candidate
    return "jpg"


def avatar_storage_path(user_id: str, upload_id: str, mime_type: str, file_name: Optional[str] = None) -> str:
    ext = avatar_extension(mime_type, file_name)
    return f"avatars/{user_id}/{upload_id}.{ext}"


async def signed_avatar_url(
    row: Optional[dict[str, Any]],
    *,
    storage: Optional[FileStorageService] = None,
) -> Optional[str]:
    if not row:
        return None

    storage_path = row.get("avatar_storage_path")
    if isinstance(storage_path, str) and storage_path.strip():
        storage_service = storage or create_file_storage_service()
        try:
            return await storage_service.get_signed_url(
                storage_path,
                expires_in=AVATAR_SIGNED_URL_EXPIRY_SECONDS,
            )
        except Exception as exc:
            logger.warning(
                "[AvatarMedia] Failed to sign avatar for user %s error_type=%s",
                row.get("id") or row.get("user_id") or row.get("userId"),
                type(exc).__name__,
            )
            return None

    legacy_url = row.get("avatar_url") or row.get("avatarUrl")
    if isinstance(legacy_url, str) and legacy_url.strip():
        return legacy_url.strip()
    return None


async def with_signed_avatar_url(
    row: Optional[dict[str, Any]],
    *,
    storage: Optional[FileStorageService] = None,
) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    out = dict(row)
    out["avatar_url"] = await signed_avatar_url(out, storage=storage)
    return out


async def with_signed_avatar_urls(
    rows: list[dict[str, Any]],
    *,
    storage: Optional[FileStorageService] = None,
) -> list[dict[str, Any]]:
    storage_service = storage
    signed: list[dict[str, Any]] = []
    for row in rows:
        if storage_service is None and row.get("avatar_storage_path"):
            storage_service = create_file_storage_service()
        signed_row = await with_signed_avatar_url(row, storage=storage_service)
        if signed_row is not None:
            signed.append(signed_row)
    return signed
