#!/usr/bin/env python3
"""Install the numbered rank-mark bake into the iOS asset catalog.

The bake itself stays ignored. This exporter validates the production manifest
before replacing only its own ``RankMarks`` asset-catalog group.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import tempfile


EXPECTED_RANKS = tuple(range(4, 51))
EXPECTED_SCALES = ("1x", "2x", "3x")
GROUP_NAME = "RankMarks"
GROUP_AUTHOR = "boulderroller-rankmarks-export"

HERE = Path(__file__).resolve().parent
REPOSITORY_ROOT = HERE.parents[1]
DEFAULT_MANIFEST = HERE / "build" / "manifest.json"
DEFAULT_ASSET_CATALOG = (
    REPOSITORY_ROOT / "ios" / "BoulderRoller" / "Resources" / "Assets.xcassets"
)


class ExportError(ValueError):
    """The bake or destination does not satisfy the import contract."""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
        help="Rank-mark manifest (default: tools/rankmarks/build/manifest.json).",
    )
    parser.add_argument(
        "--build-dir",
        type=Path,
        help="Sprite directory (default: the manifest's directory).",
    )
    parser.add_argument(
        "--asset-catalog",
        type=Path,
        default=DEFAULT_ASSET_CATALOG,
        help="Destination .xcassets catalog.",
    )
    return parser.parse_args()


def load_manifest(path: Path) -> dict:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ExportError(f"manifest is missing: {path}") from error
    except json.JSONDecodeError as error:
        raise ExportError(f"manifest is invalid JSON: {path}: {error}") from error

    if manifest.get("schema_version") != 2:
        raise ExportError("manifest schema_version must be 2")
    if not isinstance(manifest.get("codex"), dict):
        raise ExportError("manifest must carry the ratified tab codex block")
    if set(manifest.get("scales", {})) != set(EXPECTED_SCALES):
        raise ExportError("manifest must contain exactly scales 1x, 2x, and 3x")

    ranks = manifest.get("ranks")
    if not isinstance(ranks, dict):
        raise ExportError("manifest ranks must be an object")
    try:
        manifest_ranks = tuple(sorted(int(rank) for rank in ranks))
    except (TypeError, ValueError) as error:
        raise ExportError("manifest rank keys must be integers") from error
    if manifest_ranks != EXPECTED_RANKS:
        raise ExportError("manifest must contain every numbered rank from 4 through 50")

    counts = manifest.get("counts", {})
    if counts.get("ranks") != len(EXPECTED_RANKS):
        raise ExportError("manifest rank count does not match the production set")
    expected_sprite_count = len(EXPECTED_RANKS) * len(EXPECTED_SCALES)
    if counts.get("scale_sprites") != expected_sprite_count:
        raise ExportError("manifest sprite count does not match the production set")

    return manifest


def source_sprites(manifest: dict, build_dir: Path) -> dict[tuple[int, str], Path]:
    sprites: dict[tuple[int, str], Path] = {}
    source_names: set[str] = set()

    for rank in EXPECTED_RANKS:
        files = manifest["ranks"][str(rank)].get("files", {})
        for scale in EXPECTED_SCALES:
            source_name = files.get(scale)
            if not isinstance(source_name, str) or Path(source_name).name != source_name:
                raise ExportError(f"unsafe sprite filename for rank {rank} {scale}")
            if source_name in source_names:
                raise ExportError(f"duplicate sprite filename: {source_name}")
            source_names.add(source_name)

            source = build_dir / source_name
            if not source.is_file() or source.stat().st_size == 0:
                raise ExportError(
                    f"missing baked sprite: {source}\n"
                    "Regenerate the bake with "
                    "/Applications/Blender.app/Contents/MacOS/Blender "
                    "-b -P tools/rankmarks/bake.py"
                )
            sprites[(rank, scale)] = source

    return sprites


def image_set_name(rank: int) -> str:
    return f"rank{rank:02d}"


def installed_filename(image_set: str, scale: str) -> str:
    suffix = "" if scale == "1x" else f"@{scale}"
    return f"{image_set}{suffix}.png"


def write_json(path: Path, value: dict) -> None:
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_group(staging: Path, sprites: dict[tuple[int, str], Path]) -> None:
    write_json(
        staging / "Contents.json",
        {"info": {"author": GROUP_AUTHOR, "version": 1}},
    )

    for rank in EXPECTED_RANKS:
        name = image_set_name(rank)
        image_set = staging / f"{name}.imageset"
        image_set.mkdir()
        images = []
        for scale in EXPECTED_SCALES:
            filename = installed_filename(name, scale)
            shutil.copyfile(sprites[(rank, scale)], image_set / filename)
            images.append(
                {"filename": filename, "idiom": "universal", "scale": scale}
            )
        write_json(
            image_set / "Contents.json",
            {
                "images": images,
                "info": {"author": "xcode", "version": 1},
            },
        )


def target_is_exporter_owned(target: Path) -> bool:
    try:
        contents = json.loads((target / "Contents.json").read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return False
    return contents.get("info", {}).get("author") == GROUP_AUTHOR


def install_group(asset_catalog: Path, sprites: dict[tuple[int, str], Path]) -> Path:
    if not asset_catalog.is_dir() or asset_catalog.suffix != ".xcassets":
        raise ExportError(f"asset catalog does not exist: {asset_catalog}")

    target = asset_catalog / GROUP_NAME
    if target.exists() and not target_is_exporter_owned(target):
        raise ExportError(f"refusing to replace unowned asset group: {target}")

    staging = Path(tempfile.mkdtemp(prefix=f".{GROUP_NAME}-", dir=asset_catalog))
    try:
        build_group(staging, sprites)
        if target.exists():
            shutil.rmtree(target)
        staging.rename(target)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return target


def main() -> int:
    args = parse_args()
    manifest_path = args.manifest.resolve()
    build_dir = (args.build_dir or manifest_path.parent).resolve()
    asset_catalog = args.asset_catalog.resolve()

    try:
        manifest = load_manifest(manifest_path)
        sprites = source_sprites(manifest, build_dir)
        target = install_group(asset_catalog, sprites)
    except (ExportError, OSError) as error:
        raise SystemExit(f"export_ios.py: {error}") from error

    print(
        f"Installed {len(EXPECTED_RANKS)} imagesets "
        f"({len(sprites)} PNGs) in {target}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
