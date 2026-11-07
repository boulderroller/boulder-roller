"""
File Storage Service: Handles raw ride file storage in Supabase Storage.

Following Strava's pattern: store original FIT/GPX/TCX files permanently
to enable reprocessing, user download, and algorithm improvements on historical rides.

Usage:
    from .file_storage import FileStorageService, create_file_storage_service

    storage = create_file_storage_service()
    result = await storage.upload_ride_file(user_id, ride_id, file_bytes, "fit")
    signed_url = await storage.get_signed_url(result.path)
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qs, urlsplit

import httpx
from supabase import Client

from ..config import load_supabase_settings
from ..repositories.base import get_supabase_client
from .privacy_logging import scrub_log_text
from .photo_metadata import InvalidPhotoError, sanitized_photo_path, strip_photo_metadata

logger = logging.getLogger(__name__)

def _storage_log(level: int, operation: str, path: str, error: Exception | None = None) -> None:
    object_id = hashlib.sha256(path.encode()).hexdigest()[:16]
    response = getattr(error, "response", None)
    status_code = getattr(response, "status_code", None)
    extra = {"object_id": object_id, "error_code": operation}
    if error is not None:
        extra["error_type"] = type(error).__name__
    if isinstance(status_code, int):
        extra["status_code"] = status_code
    logger.log(level, "[FileStorage] %s object_id=%s error_type=%s status_code=%s message=%s",
               operation, object_id, type(error).__name__ if error else None, status_code,
               scrub_log_text(str(error).replace(path, "[redacted]")) if error else None,
               extra=extra)


# Supabase Storage bucket name
BUCKET_NAME = "ride-uploads"

# Signed URL expiry (1 hour)
SIGNED_URL_EXPIRY_SECONDS = 3600

# Max file size (50MB)
MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024
_PHOTO_DECODE_SLOT = asyncio.Semaphore(1)


@dataclass
class StorageResult:
    """Result of a successful file upload."""
    path: str
    size_bytes: int
    file_hash: str


@dataclass
class PhotoStorageResult:
    path: str
    size_bytes: int
    width: int
    height: int
    mime_type: str = "image/jpeg"


class FileStorageError(Exception):
    """Base error for file storage operations."""
    pass


class StorageUnavailableError(FileStorageError):
    """Storage service is temporarily unavailable."""
    pass


class PhotoAlreadyExistsError(FileStorageError):
    """A concurrent sanitizer won the immutable destination write."""


class FileNotFoundError(FileStorageError):
    """Requested file does not exist in storage."""
    pass


class FileTooLargeError(FileStorageError):
    """File exceeds maximum size limit."""
    pass


class FileStorageService:
    """
    Service for storing and retrieving ride files from Supabase Storage.

    Storage path structure:
        rides/{user_id}/{ride_id}.{ext}

    Example:
        rides/550e8400-e29b-41d4-a716-446655440000/7c9e6679-7425-40de-944b-e07fc1f90ae7.fit
    """

    def __init__(self, client: Optional[Client] = None):
        """
        Initialize with Supabase client.

        Args:
            client: Optional Supabase client. If not provided, uses shared client.
        """
        self._client = client or get_supabase_client()
        # Direct HTTP access for the two write paths the pinned storage3
        # client can no longer speak against hosted Supabase (empty-JSON-body
        # rejection on upload/sign; multipart envelope stored verbatim on
        # object upload). Read paths still go through the client.
        settings = load_supabase_settings()
        if settings:
            self._storage_base = f"{settings.url.rstrip('/')}/storage/v1"
            self._storage_headers = {
                "Authorization": f"Bearer {settings.service_role_key}",
                "apikey": settings.service_role_key,
            }
        else:
            self._storage_base = None
            self._storage_headers = None

    @property
    def storage(self):
        """Get Supabase Storage client."""
        return self._client.storage

    def _require_http_config(self) -> None:
        if not self._storage_base or not self._storage_headers:
            raise StorageUnavailableError(
                "Supabase storage HTTP config unavailable (missing settings)"
            )

    def compute_file_hash(self, file_bytes: bytes) -> str:
        """
        Compute SHA256 hash of file content.

        Args:
            file_bytes: Raw file content

        Returns:
            Hex-encoded SHA256 hash (64 characters)
        """
        return hashlib.sha256(file_bytes).hexdigest()

    def _build_path(self, user_id: str, ride_id: str, file_type: str) -> str:
        """
        Build storage path for a ride file.

        Args:
            user_id: User's UUID
            ride_id: Ride's UUID
            file_type: File extension (fit, gpx, tcx)

        Returns:
            Storage path string
        """
        # Normalize file type to lowercase
        ext = file_type.lower().strip(".")
        return f"rides/{user_id}/{ride_id}.{ext}"

    def _get_content_type(self, file_type: str) -> str:
        """
        Get MIME type for file extension.

        Args:
            file_type: File extension (fit, gpx, tcx)

        Returns:
            MIME type string
        """
        content_types = {
            "fit": "application/octet-stream",
            "gpx": "application/gpx+xml",
            "tcx": "application/xml",
        }
        return content_types.get(file_type.lower(), "application/octet-stream")

    async def upload_ride_file(
        self,
        user_id: str,
        ride_id: str,
        file_bytes: bytes,
        file_type: str,
    ) -> StorageResult:
        """
        Upload a ride file to Supabase Storage.

        Args:
            user_id: User's UUID
            ride_id: Ride's UUID
            file_bytes: Raw file content
            file_type: File extension (fit, gpx, tcx)

        Returns:
            StorageResult with path, size, and hash

        Raises:
            FileTooLargeError: If file exceeds 50MB limit
            StorageUnavailableError: If storage upload fails
        """
        # Validate file size
        if len(file_bytes) > MAX_FILE_SIZE_BYTES:
            raise FileTooLargeError(
                f"File size {len(file_bytes)} exceeds limit of {MAX_FILE_SIZE_BYTES} bytes"
            )

        # Compute hash for deduplication
        file_hash = self.compute_file_hash(file_bytes)

        # Build storage path
        path = self._build_path(user_id, ride_id, file_type)
        content_type = self._get_content_type(file_type)

        try:
            # Raw-bytes upload via the storage HTTP API. The pinned storage3
            # client wraps the payload in a multipart envelope that hosted
            # Supabase now stores verbatim, corrupting every ride file.
            self._require_http_config()
            async with httpx.AsyncClient(timeout=60.0) as http:
                resp = await http.post(
                    f"{self._storage_base}/object/{BUCKET_NAME}/{path}",
                    headers={
                        **self._storage_headers,
                        "Content-Type": content_type,
                        "x-upsert": "true",
                    },
                    content=file_bytes,
                )
            resp.raise_for_status()

            _storage_log(logging.INFO, "storage_uploaded", path)

            return StorageResult(
                path=path,
                size_bytes=len(file_bytes),
                file_hash=file_hash,
            )

        except Exception as e:
            _storage_log(logging.ERROR, "storage_upload_failed", path, e)
            raise StorageUnavailableError("Failed to upload file") from e

    async def download_ride_file(self, path: str) -> bytes:
        """
        Download a ride file from storage.

        Args:
            path: Storage path (e.g., "rides/{user_id}/{ride_id}.fit")

        Returns:
            Raw file bytes

        Raises:
            FileNotFoundError: If file doesn't exist
            StorageUnavailableError: If download fails
        """
        try:
            def _download():
                return self.storage.from_(BUCKET_NAME).download(path)

            result = await asyncio.to_thread(_download)

            _storage_log(logging.INFO, "storage_downloaded", path)
            return result

        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "404" in error_msg:
                raise FileNotFoundError("File not found") from e
            _storage_log(logging.ERROR, "storage_download_failed", path, e)
            raise StorageUnavailableError("Failed to download file") from e

    async def get_signed_url(
        self,
        path: str,
        expires_in: int = SIGNED_URL_EXPIRY_SECONDS
    ) -> str:
        """
        Generate a signed download URL for a file.

        Args:
            path: Storage path
            expires_in: URL validity in seconds (default 1 hour)

        Returns:
            Signed URL string

        Raises:
            StorageUnavailableError: If URL generation fails
        """
        try:
            def _create_signed_url():
                return self.storage.from_(BUCKET_NAME).create_signed_url(
                    path=path,
                    expires_in=expires_in,
                )

            result = await asyncio.to_thread(_create_signed_url)

            # Handle both camelCase and snake_case response formats
            url = result.get("signedURL") or result.get("signedUrl") or result.get("signed_url")
            if not url:
                raise StorageUnavailableError("No signed URL in response")

            _storage_log(logging.INFO, "storage_signed", path)
            return url

        except StorageUnavailableError:
            raise
        except Exception as e:
            _storage_log(logging.ERROR, "storage_sign_failed", path, e)
            raise StorageUnavailableError("Failed to generate signed URL") from e

    async def delete_ride_file(self, path: str) -> bool:
        """
        Delete a ride file from storage.

        Args:
            path: Storage path

        Returns:
            True if deleted, False if not found

        Raises:
            StorageUnavailableError: If deletion fails (other than not found)
        """
        try:
            def _delete():
                return self.storage.from_(BUCKET_NAME).remove([path])

            result = await asyncio.to_thread(_delete)

            if not isinstance(result, list):
                raise StorageUnavailableError(
                    "Storage deletion could not confirm a verifiable object list"
                )
            if not result:
                _storage_log(logging.INFO, "storage_absent", path)
                return False
            if any(not isinstance(item, dict) for item in result):
                raise StorageUnavailableError(
                    "Storage deletion could not confirm a malformed object list"
                )
            if not any(item.get("name") == path for item in result):
                raise StorageUnavailableError(
                    "Storage deletion did not confirm the requested object"
                )

            _storage_log(logging.INFO, "storage_deleted", path)
            return True

        except StorageUnavailableError:
            raise
        except Exception as e:
            error_msg = str(e).lower()
            if "not found" in error_msg or "404" in error_msg:
                _storage_log(logging.INFO, "storage_absent", path)
                return False
            _storage_log(logging.ERROR, "storage_delete_failed", path, e)
            raise StorageUnavailableError("Failed to delete file") from e

    async def create_signed_upload_url(
        self,
        path: str,
    ) -> dict:
        """
        Create a signed upload URL for direct client uploads.

        The client PUTs the raw file bytes to the returned URL.

        Args:
            path: Storage path (e.g., "rides/{user_id}/{ride_id}.fit")

        Returns:
            Dict with keys: signed_url, token, path

        Raises:
            StorageUnavailableError: If URL generation fails
        """
        if path.startswith("sanitized/"):
            raise StorageUnavailableError("Photo publication paths are server-written only")
        try:
            # Direct HTTP call: hosted Supabase now rejects the empty
            # application/json body the pinned storage3 client sends
            # (FastifyError "Body cannot be empty..."); an explicit {} passes.
            self._require_http_config()
            async with httpx.AsyncClient(timeout=30.0) as http:
                resp = await http.post(
                    f"{self._storage_base}/object/upload/sign/{BUCKET_NAME}/{path}",
                    headers={
                        **self._storage_headers,
                        "Content-Type": "application/json",
                    },
                    content=b"{}",
                )
            resp.raise_for_status()
            result = resp.json()

            rel_url = result.get("url") or result.get("signedURL") or result.get("signed_url")
            if not rel_url:
                raise StorageUnavailableError(
                    "No signed upload URL in response"
                )
            signed_url = (
                f"{self._storage_base}{rel_url}" if rel_url.startswith("/") else rel_url
            )
            token_values = parse_qs(urlsplit(signed_url).query).get("token", [])
            token = result.get("token") or (token_values[0] if token_values else "")

            _storage_log(logging.INFO, "storage_upload_signed", path)
            return {
                "signed_url": signed_url,
                "token": token,
                "path": path,
            }

        except StorageUnavailableError:
            raise
        except Exception as e:
            _storage_log(logging.ERROR, "storage_upload_sign_failed", path, e)
            raise StorageUnavailableError(
                "Failed to create signed upload URL"
            ) from e

    async def get_file_size(self, path: str) -> Optional[int]:
        """
        Get the size of a file in storage.

        Args:
            path: Storage path

        Returns:
            File size in bytes, or None if file not found
        """
        try:
            def _list():
                parent = path.rsplit("/", 1)[0]
                return self.storage.from_(BUCKET_NAME).list(path=parent)

            files = await asyncio.to_thread(_list)
            filename = path.rsplit("/", 1)[-1]
            for f in files:
                if f.get("name") == filename:
                    metadata = f.get("metadata", {})
                    size = metadata.get("size") or metadata.get("content-length")
                    if size is not None:
                        return int(size)
                    # Some Supabase versions put size at top level
                    if f.get("size") is not None:
                        return int(f["size"])
                    return None
            return None

        except Exception as e:
            _storage_log(logging.WARNING, "storage_size_failed", path, e)
            return None

    async def get_file_info(self, path: str) -> dict:
        """Read storage metadata without transferring or decoding object contents."""
        try:
            self._require_http_config()
            async with httpx.AsyncClient(timeout=30.0) as http:
                response = await http.get(
                    f"{self._storage_base}/object/info/authenticated/{BUCKET_NAME}/{path}",
                    headers=self._storage_headers,
                )
                if response.status_code == 404:
                    raise FileNotFoundError("Object not found")
                response.raise_for_status()
                info = response.json()
                if not isinstance(info, dict) or not isinstance(info.get("size"), int) or info["size"] < 0:
                    raise ValueError("Malformed object metadata")
                return info
        except FileNotFoundError:
            raise
        except Exception as exc:
            _storage_log(logging.ERROR, "storage_info_failed", path, exc)
            raise StorageUnavailableError("Object metadata unavailable") from exc

    async def upload_photo_file(self, path: str, content: bytes, mime_type: str, *, metadata: dict | None = None,
                                overwrite: bool = True) -> None:
        """Write backend-sanitized bytes without a client upload capability."""
        try:
            self._require_http_config()
            headers = {**self._storage_headers, "Content-Type": mime_type, "x-upsert": str(overwrite).lower()}
            if metadata is not None:
                headers["x-metadata"] = base64.b64encode(json.dumps(metadata).encode()).decode()
            async with httpx.AsyncClient(timeout=60.0) as http:
                response = await http.post(
                    f"{self._storage_base}/object/{BUCKET_NAME}/{path}",
                    headers=headers,
                    content=content,
                )
                if not overwrite and (response.status_code == 409 or (
                    response.status_code == 400 and response.json().get("error") == "Duplicate"
                )):
                    raise PhotoAlreadyExistsError("Photo already sanitized")
                response.raise_for_status()
        except PhotoAlreadyExistsError:
            raise
        except Exception as exc:
            _storage_log(logging.ERROR, "storage_photo_write_failed", path, exc)
            raise StorageUnavailableError("Photo storage write failed") from exc

    async def prepare_photo(self, path: str, mime_type: str, declared_size: int) -> PhotoStorageResult:
        """Sanitize, verify storage, then remove the private upload original.

        Use a distinct server-only destination so an outstanding upload URL
        cannot replace the published bytes. Deterministic paths permit retries
        after cleanup succeeds but the database promotion fails.
        """
        destination = sanitized_photo_path(path)
        try:
            info = await self.get_file_info(destination)
        except FileNotFoundError:
            info = None
        receipt = (info or {}).get("metadata") or {}
        if receipt.get("photo_sanitizer_version") != 1:
            original = await self.download_ride_file(path)
            if declared_size > 0 and not declared_size * 0.5 <= len(original) <= declared_size * 1.1:
                raise InvalidPhotoError("Photo size does not match declared size")
            async with _PHOTO_DECODE_SLOT:
                photo = await asyncio.to_thread(strip_photo_metadata, original, mime_type)
            receipt = {"photo_sanitizer_version": 1, "width": photo.width, "height": photo.height,
                       "mime_type": photo.mime_type, "sha256": hashlib.sha256(photo.content).hexdigest()}
            try:
                await self.upload_photo_file(destination, photo.content, photo.mime_type, metadata=receipt, overwrite=False)
            except PhotoAlreadyExistsError:
                pass  # Verify and reuse the winner; never replace a published object.
            info = await self.get_file_info(destination)
            receipt = info.get("metadata") or {}
            if receipt.get("photo_sanitizer_version") != 1:
                raise StorageUnavailableError("Photo receipt could not be verified")
        # A backend-only receipt binds the stored bytes and dimensions. Retrying
        # after a DB/cleanup failure verifies the hash, never re-decodes pixels.
        content = await self.download_ride_file(destination)
        if (len(content) != info["size"] or hashlib.sha256(content).hexdigest() != receipt.get("sha256")
                or receipt.get("mime_type") not in ("image/jpeg", "image/png", "image/webp")
                or any(not isinstance(receipt.get(k), int) or not 0 < receipt[k] <= 4096 for k in ("width", "height"))):
            raise StorageUnavailableError("Photo storage write could not be verified")
        await self.delete_ride_file(path)
        if await self.file_exists_strict(path):
            raise StorageUnavailableError("Photo original cleanup could not be verified")
        return PhotoStorageResult(destination, len(content), receipt["width"], receipt["height"], receipt["mime_type"])

    async def delete_photo_files(self, path: str) -> int:
        """Remove both exact lifecycle paths before discarding their DB reference."""
        original = path.removeprefix("sanitized/")
        deleted = 0
        for target in (original, sanitized_photo_path(original)):
            deleted += bool(await self.delete_ride_file(target))
            if await self.file_exists_strict(target):
                raise StorageUnavailableError("Photo cleanup could not be verified")
        return deleted

    async def file_exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.

        Args:
            path: Storage path

        Returns:
            True if file exists, False otherwise
        """
        try:
            # Try to get file info by listing with exact path prefix
            def _list():
                return self.storage.from_(BUCKET_NAME).list(path=path.rsplit("/", 1)[0])

            files = await asyncio.to_thread(_list)
            filename = path.rsplit("/", 1)[-1]
            return any(f.get("name") == filename for f in files)

        except Exception:
            return False

    async def file_exists_strict(self, path: str) -> bool:
        """Check object presence without translating storage outages to absence."""
        try:
            parent, separator, filename = path.rpartition("/")
            if not separator:
                parent, filename = "", path
            page_size = 100
            offset = 0
            prior_page: tuple[str, ...] | None = None

            while True:
                def _list():
                    return self.storage.from_(BUCKET_NAME).list(
                        path=parent,
                        options={
                            "limit": page_size,
                            "offset": offset,
                            "sortBy": {"column": "name", "order": "asc"},
                        },
                    )

                files = await asyncio.to_thread(_list)
                if not isinstance(files, list) or any(
                    not isinstance(item, dict) or not isinstance(item.get("name"), str)
                    for item in files
                ):
                    raise StorageUnavailableError(
                        "Storage listing returned a malformed object list"
                    )
                names = tuple(item["name"] for item in files)
                if filename in names:
                    return True
                if len(files) < page_size:
                    return False
                if names == prior_page:
                    raise StorageUnavailableError(
                        "Storage listing pagination did not advance"
                    )
                prior_page = names
                offset += page_size
        except StorageUnavailableError:
            raise
        except Exception as exc:
            _storage_log(logging.ERROR, "storage_check_failed", path, exc)
            raise StorageUnavailableError(
                "Failed to confirm storage object absence"
            ) from exc


# Factory function
def create_file_storage_service(client: Optional[Client] = None) -> FileStorageService:
    """
    Create a FileStorageService instance.

    Args:
        client: Optional Supabase client

    Returns:
        FileStorageService instance
    """
    return FileStorageService(client)
