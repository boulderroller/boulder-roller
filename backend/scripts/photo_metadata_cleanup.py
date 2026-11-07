"""One-off photo cleanup against an explicitly reviewed path manifest.

Dry-run by default. The manifest is [{"path": "avatars/...", "mime_type":
"image/jpeg"}, ...], covering ride_media.storage_path, users.avatar_storage_path
and users.avatar_pending_storage_path / avatar_cleanup_storage_paths, plus any reviewed orphan photo objects.
Run from backend: python -m scripts.photo_metadata_cleanup --manifest photos.json
--archive /private/photo-archive [--apply]. Restore with --restore --archive ...
[--apply]. Apply/restore require --uploads-quiesced: stop photo mutations and
wait for outstanding provider upload capabilities to expire before selecting
the manifest. Compare-and-write is not atomic. Never supply raw ride-file
paths. The reviewed manifest identifies DB metadata to update and restore.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import re


from app.services.photo_metadata import FORMATS, strip_photo_metadata


def _hash(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def _validate(item: dict) -> None:
    path = item.get("path", "")
    if not isinstance(path, str) or not path.startswith(("avatars/", "ride-media/", "sanitized/avatars/", "sanitized/ride-media/")):
        raise ValueError("Manifest contains a non-photo path")
    if any(part in {"", ".", ".."} for part in path.split("/")) or "\\" in path:
        raise ValueError("Invalid manifest path")
    if item.get("mime_type") not in FORMATS:
        raise ValueError("Invalid manifest media type")


def _archive(archive: Path, item: dict, original: bytes, replacement: bytes) -> None:
    if archive.is_symlink():
        raise ValueError("Archive must not be a symlink")
    archive.mkdir(mode=0o700, parents=True, exist_ok=True)
    archive.chmod(0o700)
    digest = _hash(original)
    backup_name = digest + ".original"
    backup = archive / backup_name
    if backup.exists():
        if backup.is_symlink() or _hash(backup.read_bytes()) != digest:
            raise ValueError("Archive verification failed")
    else:
        with backup.open("xb") as output:
            os.fchmod(output.fileno(), 0o600)
            output.write(original)
            output.flush()
            os.fsync(output.fileno())
    receipt = {**item, "backup_file": backup_name, "original_sha256": digest, "sanitized_sha256": _hash(replacement)}
    manifest = archive / "manifest.jsonl"
    if manifest.is_symlink():
        raise ValueError("Archive manifest must not be a symlink")
    with manifest.open("a") as output:
        os.fchmod(output.fileno(), 0o600)
        output.write(json.dumps(receipt) + "\n")
        output.flush()
        os.fsync(output.fileno())
    directory = os.open(archive, os.O_RDONLY)
    try:
        os.fsync(directory)
    finally:
        os.close(directory)


async def _update_metadata(db, item, photo, size, *, restore=False):
    for reference in item.get("references", []):
        table, field = reference["table"], reference["path_column"]
        if (table, field) not in {("ride_media", "storage_path"), ("users", "avatar_storage_path"),
                                  ("users", "avatar_pending_storage_path")}:
            raise ValueError("Invalid metadata reference")
        if db is None:
            raise ValueError("Database required for referenced photo metadata")
        if restore:
            payload = reference["metadata"]
        elif table == "ride_media":
            payload = {"width": photo.width, "height": photo.height, "size_bytes": size, "mime_type": photo.mime_type}
        else:
            prefix = "avatar_pending" if field == "avatar_pending_storage_path" else "avatar"
            payload = {prefix + "_size_bytes": size, prefix + "_mime_type": photo.mime_type}
        allowed = ({"width", "height", "size_bytes", "mime_type"} if table == "ride_media" else
                   {"avatar_size_bytes", "avatar_mime_type"} if field == "avatar_storage_path" else
                   {"avatar_pending_size_bytes", "avatar_pending_mime_type"})
        if set(payload) != allowed:
            raise ValueError("Invalid metadata fields")
        def update():
            return db.table(table).update(payload).eq("id", reference["id"]).eq(field, item["path"]).execute()
        result = await asyncio.to_thread(update)
        if not isinstance(result.data, list) or len(result.data) != 1:
            raise ValueError("Photo metadata reference changed")


async def clean(storage, manifest: list[dict], *, archive: Path, apply: bool = False, db=None) -> dict:
    seen = set()
    for item in manifest:
        _validate(item)
        if item["path"] in seen:
            raise ValueError("Duplicate manifest path")
        seen.add(item["path"])
    result = {"paths": len(manifest), "with_metadata": 0, "changed": 0, "failures": []}
    for item in manifest:
        try:
            original = await storage.download_ride_file(item["path"])
            photo = await asyncio.to_thread(strip_photo_metadata, original, item["mime_type"])
            needs_write = photo.had_metadata or photo.resized or photo.mime_type != item["mime_type"]
            if photo.had_metadata:
                result["with_metadata"] += 1
            if not apply:
                continue
            replacement = photo.content if needs_write else original
            _archive(archive, item, original, replacement)
            if await storage.download_ride_file(item["path"]) != original:
                raise ValueError("Object changed during cleanup")
            if needs_write:
                metadata = {"photo_sanitizer_version": 1, "width": photo.width, "height": photo.height,
                            "mime_type": photo.mime_type, "sha256": _hash(replacement)}
                await storage.upload_photo_file(item["path"], replacement, photo.mime_type, metadata=metadata)
                if await storage.download_ride_file(item["path"]) != replacement:
                    raise ValueError("Cleanup verification failed")
            await _update_metadata(db, item, photo, len(replacement))
            result["changed"] += int(needs_write)
        except Exception as error:
            result["failures"].append({"path": item["path"], "error_type": type(error).__name__})
    return result


async def restore(storage, *, archive: Path, apply: bool = False, db=None) -> int:
    receipts = [json.loads(line) for line in (archive / "manifest.jsonl").read_text().splitlines()]
    changed = 0
    for receipt in reversed(receipts):
        _validate(receipt)
        name = receipt["backup_file"]
        if not re.fullmatch(r"[a-f0-9]{64}\.original", name):
            raise ValueError("Invalid backup path")
        backup = archive / name
        if backup.is_symlink():
            raise ValueError("Invalid backup path")
        original = backup.read_bytes()
        if _hash(original) != receipt["original_sha256"]:
            raise ValueError("Backup verification failed")
        current = await storage.download_ride_file(receipt["path"])
        if current == original:
            if apply:
                await _update_metadata(db, receipt, None, len(original), restore=True)
            continue
        if _hash(current) != receipt["sanitized_sha256"]:
            raise ValueError("Object changed since cleanup; restore refused")
        if apply:
            await storage.upload_photo_file(receipt["path"], original, receipt["mime_type"])
            if await storage.download_ride_file(receipt["path"]) != original:
                raise ValueError("Restore verification failed")
            await _update_metadata(db, receipt, None, len(original), restore=True)
            changed += 1
    return changed


async def _main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--restore", action="store_true")
    parser.add_argument("--uploads-quiesced", action="store_true")
    args = parser.parse_args()
    if not args.restore and args.manifest is None:
        parser.error("--manifest is required for cleanup")
    if args.apply and not args.uploads_quiesced:
        parser.error("--apply requires --uploads-quiesced after photo mutations stop and upload capabilities expire")
    from app.services.file_storage import create_file_storage_service
    storage = create_file_storage_service()
    if args.restore:
        result = {"restored": await restore(storage, archive=args.archive, apply=args.apply, db=storage._client)}
    else:
        result = await clean(storage, json.loads(args.manifest.read_text()), archive=args.archive, apply=args.apply, db=storage._client)
    print(json.dumps({"dry_run": not args.apply, **result}))
    if result.get("failures"):
        raise SystemExit(1)


if __name__ == "__main__":
    try:
        asyncio.run(_main())
    except Exception as error:
        # Provider exception text can contain signed URLs and exact paths.
        print(json.dumps({"error_type": type(error).__name__, "completed": False}))
        raise SystemExit(1) from None
