from io import BytesIO

from PIL import Image
import pytest

from backend.scripts import photo_metadata_cleanup
from backend.tests.routes.test_photo_metadata import MemoryStorage, photo_bytes


@pytest.mark.asyncio
async def test_cleanup_dry_run_archives_before_write_and_can_restore(tmp_path):
    path = "avatars/11111111-1111-4111-8111-111111111111/photo.jpg"
    original = photo_bytes()
    storage = MemoryStorage(path, original)
    manifest = [{"path": path, "mime_type": "image/jpeg"}]
    archive = tmp_path / "archive"
    result = await photo_metadata_cleanup.clean(storage, manifest, archive=archive)
    assert result == {"paths": 1, "with_metadata": 1, "changed": 0, "failures": []}
    assert storage.objects[path] == original
    assert not archive.exists()
    result = await photo_metadata_cleanup.clean(storage, manifest, archive=archive, apply=True)
    assert result["changed"] == 1
    assert not Image.open(BytesIO(storage.objects[path])).getexif()
    assert (archive.stat().st_mode & 0o777) == 0o700
    assert await photo_metadata_cleanup.restore(storage, archive=archive) == 0
    assert storage.objects[path] != original
    assert await photo_metadata_cleanup.restore(storage, archive=archive, apply=True) == 1
    assert storage.objects[path] == original


@pytest.mark.asyncio
async def test_cleanup_continues_after_failed_photo_and_reports_path(tmp_path):
    bad = "avatars/owner/broken.jpg"
    good = "avatars/owner/good.jpg"
    storage = MemoryStorage(bad, b"invalid image")
    storage.objects[good] = photo_bytes()
    result = await photo_metadata_cleanup.clean(storage, [
        {"path": bad, "mime_type": "image/jpeg"}, {"path": good, "mime_type": "image/jpeg"},
    ], archive=tmp_path / "archive", apply=True)
    assert result["changed"] == 1
    assert result["failures"][0]["path"] == bad
    assert not Image.open(BytesIO(storage.objects[good])).getexif()


@pytest.mark.asyncio
async def test_cleanup_updates_dimensions_size_and_mime_and_restore_metadata(tmp_path):
    from types import SimpleNamespace
    path = "ride-media/owner/ride/photo.heic"
    original = photo_bytes("HEIF")
    storage = MemoryStorage(path, original)
    old = {"width": 100, "height": 100, "size_bytes": len(original), "mime_type": "image/heic"}
    row = {"id": "photo", "storage_path": path, **old}
    class Query:
        def update(self, payload): self.payload = payload; return self
        def eq(self, key, value): assert row[key] == value; return self
        def execute(self): row.update(self.payload); return SimpleNamespace(data=[row.copy()])
    db = SimpleNamespace(table=lambda name: Query())
    manifest = [{"path": path, "mime_type": "image/heic", "references": [
        {"table": "ride_media", "id": "photo", "path_column": "storage_path", "metadata": old},
    ]}]
    archive = tmp_path / "archive"
    result = await photo_metadata_cleanup.clean(storage, manifest, archive=archive, apply=True, db=db)
    assert result["failures"] == []
    assert (row["width"], row["height"]) == Image.open(BytesIO(storage.objects[path])).size
    assert row["size_bytes"] == len(storage.objects[path])
    assert row["mime_type"] == "image/jpeg"
    assert await photo_metadata_cleanup.restore(storage, archive=archive, apply=True, db=db) == 1
    assert all(row[k] == v for k, v in old.items())
