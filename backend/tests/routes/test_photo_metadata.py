from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

from PIL import Image, ImageOps
from pillow_heif import register_heif_opener
from fastapi import HTTPException
import pytest

from app.dependencies import AuthenticatedUser
from app.routes import rides, users
from app.schemas import AvatarUploadCompleteRequest, RideMediaCompleteRequest
from app.services.file_storage import FileStorageService, FileNotFoundError, StorageUnavailableError


UID = "11111111-1111-4111-8111-111111111111"
RID = "22222222-2222-4222-8222-222222222222"
MID = "33333333-3333-4333-8333-333333333333"
CURRENT = AuthenticatedUser("fixture-wallet", UID, "device")


def photo_bytes(fmt="JPEG"):
    register_heif_opener(thumbnails=False)
    image = Image.new("RGB", (24, 16), "red")
    exif = Image.Exif()
    exif[274] = 6
    exif[270] = "Private Rider"
    exif[34853] = {1: "N", 2: (40.0, 7.0, 24.0), 3: "W", 4: (79.0, 59.0, 15.0)}
    output = BytesIO()
    image.save(output, format=fmt, exif=exif, xmp=b'<xmp>GPSLatitude="40.123456"</xmp>')
    return output.getvalue()


class MemoryStorage(FileStorageService):
    def __init__(self, path, content):
        self.objects = {path: content}
        self.fail_delete = False
        self.metadata = {}

    async def file_exists(self, path):
        return path in self.objects

    file_exists_strict = file_exists

    async def get_file_size(self, path):
        return len(self.objects[path]) if path in self.objects else None

    async def download_ride_file(self, path):
        if path not in self.objects:
            raise FileNotFoundError("File not found")
        return self.objects[path]

    async def get_file_info(self, path):
        if path not in self.objects:
            raise FileNotFoundError("absent")
        return {"size": len(self.objects[path]), "metadata": self.metadata.get(path, {})}

    async def upload_photo_file(self, path, content, mime_type, *, metadata=None, overwrite=True):
        self.objects[path] = content
        self.metadata[path] = metadata or {}

    async def delete_ride_file(self, path):
        if self.fail_delete:
            raise StorageUnavailableError("storage unavailable")
        return self.objects.pop(path, None) is not None

    async def get_signed_url(self, path, **kwargs):
        return f"https://local.invalid/{path}"


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ride", "avatar"])
@pytest.mark.parametrize("fmt,mime,extension", [
    ("JPEG", "image/jpeg", "jpg"), ("PNG", "image/png", "png"),
    ("WEBP", "image/webp", "webp"), ("HEIF", "image/heic", "heic"),
])
async def test_upload_is_sanitized_before_becoming_readable(monkeypatch, surface, fmt, mime, extension):
    path = f"ride-media/{UID}/{RID}/{MID}.{extension}" if surface == "ride" else f"avatars/{UID}/{MID}.{extension}"
    original = photo_bytes(fmt)
    assert Image.open(BytesIO(original)).getexif()
    expected_size = ImageOps.exif_transpose(Image.open(BytesIO(original))).size
    storage = MemoryStorage(path, original)
    monkeypatch.setattr(rides, "create_file_storage_service", lambda: storage)
    monkeypatch.setattr(users, "create_file_storage_service", lambda: storage)
    promoted = {}
    if surface == "ride":
        media = {"id": MID, "ride_id": RID, "user_id": UID, "storage_path": path,
                 "mime_type": mime, "size_bytes": len(original), "upload_status": "uploading"}
        async def complete(media_id, **kwargs):
            promoted.update({**media, **kwargs, "upload_status": "ready"})
            return promoted
        repo = SimpleNamespace(get_ride_media=AsyncMock(return_value=media),
                               complete_ride_media_upload=AsyncMock(side_effect=complete))
        await rides.ride_media_upload_complete(http_request=None, ride_id=RID,
            complete_request=RideMediaCompleteRequest(media_id=MID), current_user=CURRENT, ride_repo=repo)
        final_path = promoted["storage_path"]
    else:
        profile = {"id": UID, "avatar_pending_upload_id": MID, "avatar_pending_storage_path": path,
                   "avatar_pending_mime_type": mime, "avatar_pending_size_bytes": len(original)}
        async def complete(**kwargs):
            promoted.update(kwargs)
            return {"id": UID}
        repo = SimpleNamespace(get_private_user_profile=AsyncMock(return_value=profile),
                               complete_avatar_upload=AsyncMock(side_effect=complete))
        monkeypatch.setattr(users, "load_private_user_profile", AsyncMock(return_value={}))
        await users.avatar_upload_complete(complete_request=AvatarUploadCompleteRequest(upload_id=MID),
                                          current_user=CURRENT, user_repo=repo, ride_repo=None)
        final_path = promoted.get("storage_path", path)
    stored = Image.open(BytesIO(storage.objects[final_path]))
    assert not stored.getexif()
    assert not stored.info.get("xmp")
    assert "Private Rider".encode() not in storage.objects[final_path]
    assert stored.size == expected_size
    assert promoted["mime_type"] == ("image/jpeg" if fmt == "HEIF" else mime)
    assert final_path != path  # The upload token must never overwrite the readable object.
    assert path not in storage.objects


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ride", "avatar"])
async def test_cleanup_failure_keeps_database_references_for_retry(monkeypatch, surface):
    path = f"avatars/{UID}/{MID}.jpg"
    storage = MemoryStorage(path, photo_bytes())
    storage.fail_delete = True
    monkeypatch.setattr(rides, "create_file_storage_service", lambda: storage)
    monkeypatch.setattr(users, "create_file_storage_service", lambda: storage)
    repo = SimpleNamespace(
        get_ride_media=AsyncMock(return_value={"id": MID, "ride_id": RID, "user_id": UID, "storage_path": path}),
        get_ride=AsyncMock(return_value={"id": RID, "user_id": UID}),
        get_private_user_profile=AsyncMock(return_value={"avatar_storage_path": path}),
        delete_ride_media=AsyncMock(), delete_avatar=AsyncMock(),
    )
    monkeypatch.setattr(users, "load_private_user_profile", AsyncMock(return_value={}))
    with pytest.raises(HTTPException) as error:
        if surface == "ride":
            await rides.delete_ride_media(RID, MID, current_user=CURRENT, ride_repo=repo)
        else:
            await users.delete_my_avatar(current_user=CURRENT, user_repo=repo, ride_repo=None)
    assert error.value.status_code == 503
    repo.delete_ride_media.assert_not_awaited()
    repo.delete_avatar.assert_not_awaited()


@pytest.mark.asyncio
async def test_avatar_database_failure_preserves_active_photo(monkeypatch):
    old = f"sanitized/avatars/{UID}/old.jpg"
    pending = f"avatars/{UID}/{MID}.jpg"
    original = photo_bytes()
    storage = MemoryStorage(pending, original)
    storage.objects[old] = b"existing avatar"
    profile = {"id": UID, "avatar_storage_path": old, "avatar_pending_upload_id": MID,
               "avatar_pending_storage_path": pending, "avatar_pending_mime_type": "image/jpeg",
               "avatar_pending_size_bytes": len(original)}
    repo = SimpleNamespace(get_private_user_profile=AsyncMock(return_value=profile),
                           complete_avatar_upload=AsyncMock(side_effect=RuntimeError("database unavailable")))
    monkeypatch.setattr(users, "create_file_storage_service", lambda: storage)
    with pytest.raises(RuntimeError):
        await users.avatar_upload_complete(complete_request=AvatarUploadCompleteRequest(upload_id=MID),
                                          current_user=CURRENT, user_repo=repo, ride_repo=None)
    assert storage.objects[old] == b"existing avatar"
    assert f"sanitized/{pending}" in storage.objects  # Still addressable through the pending row.


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ride_delete", "stale_cleanup"])
async def test_cleanup_removes_sanitized_photo_after_failed_database_promotion(monkeypatch, surface):
    from app.routes import admin
    from unittest.mock import MagicMock
    path = f"ride-media/{UID}/{RID}/{MID}.jpg"
    storage = MemoryStorage(f"sanitized/{path}", b"already sanitized")
    repo = SimpleNamespace(list_ride_media=AsyncMock(return_value=[{"id": MID, "storage_path": path}]),
                           list_stale_ride_media_uploads=AsyncMock(return_value=[{"id": MID, "storage_path": path}]),
                           delete_ride_media=AsyncMock())
    monkeypatch.setattr(rides, "create_file_storage_service", lambda: storage)
    monkeypatch.setattr(admin, "create_file_storage_service", lambda: storage)
    if surface == "ride_delete":
        await rides._delete_ride_storage_objects({"id": RID}, repo)
    else:
        result = await admin.cleanup_stale_ride_media(request=MagicMock(), older_than_hours=24,
                                                    limit=100, admin_ctx=(UID, "admin"), ride_repo=repo)
        assert result.failed == 0
    assert not storage.objects


@pytest.mark.asyncio
async def test_avatar_cleanup_failure_retains_reference_and_complete_can_retry(monkeypatch):
    from app.repositories.user import UserRepository
    old = f"sanitized/avatars/{UID}/old.jpg"
    pending = f"avatars/{UID}/{MID}.jpg"
    content = photo_bytes()
    storage = MemoryStorage(pending, content)
    storage.objects[old] = b"prior avatar"
    profile = {"id": UID, "avatar_storage_path": old, "avatar_cleanup_storage_paths": [],
               "avatar_pending_upload_id": MID, "avatar_pending_storage_path": pending,
               "avatar_pending_mime_type": "image/jpeg", "avatar_pending_size_bytes": len(content)}

    class Query:
        def update(self, payload):
            self.payload, self.filters = payload, {}
            return self
        def eq(self, key, value):
            if key == "avatar_cleanup_storage_paths":
                # PostgREST encodes criteria literally: Python list repr is
                # not PostgreSQL array input syntax.
                import json
                assert isinstance(value, str) and value.startswith("{") and value.endswith("}")
                value = json.loads("[" + value[1:-1] + "]")
            self.filters[key] = value
            return self
        def execute(self):
            if any(profile.get(key) != value for key, value in self.filters.items()):
                return SimpleNamespace(data=[])
            profile.update(self.payload)
            return SimpleNamespace(data=[dict(profile)])

    repo = UserRepository(SimpleNamespace(table=lambda _: Query()))
    repo._run = AsyncMock(side_effect=lambda fn: fn())
    repo.get_user_by_id = AsyncMock(side_effect=lambda _: dict(profile))
    repo.get_private_user_profile = AsyncMock(side_effect=lambda _: dict(profile))
    original_delete = storage.delete_ride_file
    async def fail_only_old(path):
        if path == old:
            raise StorageUnavailableError("storage unavailable")
        return await original_delete(path)
    storage.delete_ride_file = fail_only_old
    monkeypatch.setattr(users, "create_file_storage_service", lambda: storage)
    monkeypatch.setattr(users, "load_private_user_profile", AsyncMock(return_value={}))
    with pytest.raises(HTTPException) as error:
        await users.avatar_upload_complete(complete_request=AvatarUploadCompleteRequest(upload_id=MID),
                                          current_user=CURRENT, user_repo=repo, ride_repo=None)
    assert error.value.status_code == 503
    assert profile["avatar_storage_path"] == f"sanitized/{pending}"
    assert profile["avatar_cleanup_storage_paths"] == [old]
    storage.delete_ride_file = original_delete
    await users.avatar_upload_complete(complete_request=AvatarUploadCompleteRequest(upload_id=MID),
                                      current_user=CURRENT, user_repo=repo, ride_repo=None)
    assert profile["avatar_cleanup_storage_paths"] == []
    assert list(storage.objects) == [f"sanitized/{pending}"]


def test_mpf_jpeg_keeps_primary_frame_and_colour_profile():
    from app.services.photo_metadata import strip_photo_metadata
    from PIL import ImageCms
    profile = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    primary = Image.new("RGB", (24, 16), "red")
    secondary = Image.new("RGB", (24, 16), "blue")
    output = BytesIO()
    primary.save(output, format="MPO", save_all=True, append_images=[secondary], icc_profile=profile)
    assert Image.open(BytesIO(output.getvalue())).format == "MPO"
    photo = strip_photo_metadata(output.getvalue(), "image/jpeg")
    with Image.open(BytesIO(photo.content)) as clean:
        assert clean.format == "JPEG"
        assert getattr(clean, "n_frames", 1) == 1
        assert clean.getpixel((0, 0))[0] > 240
        assert clean.info["icc_profile"] == profile
        assert not clean.getexif()


def test_sixty_megapixel_panorama_is_downscaled():
    from app.services.photo_metadata import strip_photo_metadata
    output = BytesIO()
    with Image.new("RGB", (10000, 6000), "green") as image:
        image.save(output, format="JPEG", quality=90)
    photo = strip_photo_metadata(output.getvalue(), "image/jpeg")
    assert (photo.width, photo.height) == (4096, 2458)
    assert len(photo.content) < 15 * 1024 * 1024


def test_heic_transcodes_in_limited_empty_environment_subprocess(monkeypatch):
    from app.services import photo_metadata
    import subprocess
    output = BytesIO()
    with Image.new("RGB", (4032, 3024), "red") as image:
        register_heif_opener(thumbnails=False)
        image.save(output, format="HEIF", quality=75)
    source = output.getvalue()
    real_run = subprocess.Popen
    calls = []
    def run(*args, **kwargs):
        calls.append((args, kwargs))
        return real_run(*args, **kwargs)
    monkeypatch.setattr(subprocess, "Popen", run)
    monkeypatch.setenv("BACKEND_SECRET_TEST", "must-not-reach-decoder")
    photo = photo_metadata.strip_photo_metadata(source, "image/heic")
    assert Image.open(BytesIO(photo.content)).format == "JPEG"
    assert photo.mime_type == "image/jpeg"
    calls = [call for call in calls if "photo_decode_worker.py" in str(call[0])]
    assert len(calls) == 1
    assert calls[0][1]["env"] == {}
    assert calls[0][1]["close_fds"] is True
    assert photo.decode_limits["cpu_seconds"] == 14
    assert photo.decode_limits["memory_bytes"] <= 1024**3


@pytest.mark.asyncio
async def test_sanitized_retry_verifies_receipt_without_decode(monkeypatch):
    from app.services import file_storage
    from unittest.mock import Mock
    original = photo_bytes()
    path = f"avatars/{UID}/{MID}.jpg"
    storage = MemoryStorage(path, original)
    decode = Mock(wraps=file_storage.strip_photo_metadata)
    monkeypatch.setattr(file_storage, "strip_photo_metadata", decode)
    first = await storage.prepare_photo(path, "image/jpeg", len(original))
    second = await storage.prepare_photo(path, "image/jpeg", len(original))
    assert first == second
    assert decode.call_count == 1
    storage.objects[first.path] = b"tampered"
    with pytest.raises(StorageUnavailableError):
        await storage.prepare_photo(path, "image/jpeg", len(original))
    assert decode.call_count == 1


def test_heif_declared_primary_image_is_preserved():
    import pillow_heif
    from app.services.photo_metadata import strip_photo_metadata
    images = pillow_heif.from_pillow(Image.new("RGB", (24, 16), "red"))
    images.add_from_pillow(Image.new("RGB", (16, 24), "blue"))
    output = BytesIO()
    images.save(output, primary_index=1)
    photo = strip_photo_metadata(output.getvalue(), "image/heic")
    clean = Image.open(BytesIO(photo.content))
    assert clean.size == (16, 24)
    assert clean.getpixel((0, 0))[2] > 240


def test_decoder_timeout_is_killed_and_fails_closed(monkeypatch, caplog):
    import subprocess
    from unittest.mock import MagicMock
    from app.services import photo_metadata
    process = MagicMock()
    from unittest.mock import Mock
    monkeypatch.setattr(photo_metadata, "_capture_decoder", Mock(side_effect=subprocess.TimeoutExpired("decoder", 15)))
    process.returncode = -9
    process.poll.return_value = None
    monkeypatch.setattr(photo_metadata.subprocess, "Popen", lambda *a, **kw: process)
    monkeypatch.setattr(photo_metadata, "_limit_rss", lambda *a: None)
    with pytest.raises(photo_metadata.InvalidPhotoError):
        photo_metadata.strip_photo_metadata(b"input", "image/jpeg")
    process.kill.assert_called_once()
    process.wait.assert_called_once()
    assert "reason=wall_timeout exit_code=-9" in caplog.text


def test_grayscale_png_transparency_survives():
    from app.services.photo_metadata import strip_photo_metadata
    output = BytesIO()
    Image.new("L", (16, 16), 100).save(output, format="PNG", transparency=100)
    photo = strip_photo_metadata(output.getvalue(), "image/png")
    clean = Image.open(BytesIO(photo.content)).convert("RGBA")
    assert clean.getpixel((0, 0))[3] == 0


def test_decoder_output_limit_is_logged_without_capturing_image_data(monkeypatch, caplog):
    import subprocess, sys
    from app.services import photo_metadata
    real_popen = subprocess.Popen
    def oversized_child(*args, **kwargs):
        return real_popen([sys.executable, "-I", "-c", "import sys; sys.stdout.buffer.write(b'private-image' * 10000)"], **kwargs)
    monkeypatch.setattr(photo_metadata, "MAX_DECODER_OUTPUT", 128, raising=False)
    monkeypatch.setattr(photo_metadata.subprocess, "Popen", oversized_child)
    with pytest.raises(photo_metadata.InvalidPhotoError):
        photo_metadata.strip_photo_metadata(b"input", "image/jpeg")
    assert "reason=output_limit" in caplog.text
    assert "exit_code=" in caplog.text
    assert "private-image" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("surface", ["ride", "avatar"])
async def test_rejected_photos_log_safe_reason_and_exit_code(monkeypatch, caplog, surface):
    path = f"ride-media/{UID}/{RID}/{MID}.jpg" if surface == "ride" else f"avatars/{UID}/{MID}.jpg"
    storage = MemoryStorage(path, b"private-invalid-image")
    monkeypatch.setattr(rides, "create_file_storage_service", lambda: storage)
    monkeypatch.setattr(users, "create_file_storage_service", lambda: storage)
    with pytest.raises(HTTPException) as error:
        if surface == "ride":
            repo = SimpleNamespace(get_ride_media=AsyncMock(return_value={
                "id": MID, "ride_id": RID, "user_id": UID, "storage_path": path,
                "mime_type": "image/jpeg", "size_bytes": len(storage.objects[path]), "upload_status": "uploading"}))
            await rides.ride_media_upload_complete(http_request=None, ride_id=RID,
                complete_request=RideMediaCompleteRequest(media_id=MID), current_user=CURRENT, ride_repo=repo)
        else:
            repo = SimpleNamespace(get_private_user_profile=AsyncMock(return_value={
                "avatar_pending_upload_id": MID, "avatar_pending_storage_path": path,
                "avatar_pending_mime_type": "image/jpeg", "avatar_pending_size_bytes": len(storage.objects[path])}))
            await users.avatar_upload_complete(complete_request=AvatarUploadCompleteRequest(upload_id=MID),
                current_user=CURRENT, user_repo=repo, ride_repo=None)
    assert error.value.status_code == 400
    assert any(record.name == f"app.routes.{('rides' if surface == 'ride' else 'users')}" and
               "reason=decode_failed" in record.getMessage() and "exit_code=1" in record.getMessage()
               for record in caplog.records)
    assert "private-invalid-image" not in caplog.text
    assert UID not in caplog.text
