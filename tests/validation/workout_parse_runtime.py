#!/usr/bin/env python3
"""
Helpers for running validation scripts against a fresh local workout_parse build.

The local Python extension can silently drift behind Rust source edits because
the repo loads the extension from workout-parse/python/workout_parse directly.
Validation tools should call `import_workout_parse_verified()` before importing
workout_parse so reports and scorecards never run stale binaries by accident.
"""

from __future__ import annotations

import importlib
import os
import shutil
import subprocess
import sys
import sysconfig
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKOUT_PARSE_DIR = REPO_ROOT / "workout-parse"
PACKAGE_DIR = WORKOUT_PARSE_DIR / "python" / "workout_parse"
SOURCE_GLOBS = [
    "Cargo.toml",
    "build.rs",
    "pyproject.toml",
    "src/**/*.rs",
    "python/workout_parse/__init__.py",
]


def _release_library_suffix() -> str:
    if sys.platform == "darwin":
        return ".dylib"
    if os.name == "nt":
        return ".dll"
    return ".so"


def release_library_path() -> Path:
    return WORKOUT_PARSE_DIR / "target" / "release" / f"libworkout_parse{_release_library_suffix()}"


def extension_suffix() -> str:
    return sysconfig.get_config_var("EXT_SUFFIX") or ".so"


def package_extension_path() -> Path:
    existing = sorted(PACKAGE_DIR.glob("workout_parse*.so")) + sorted(PACKAGE_DIR.glob("workout_parse*.pyd"))
    if existing:
        return existing[0]
    return PACKAGE_DIR / f"workout_parse{extension_suffix()}"


def latest_source_mtime() -> float:
    latest = 0.0
    for pattern in SOURCE_GLOBS:
        for path in WORKOUT_PARSE_DIR.glob(pattern):
            if path.is_file():
                latest = max(latest, path.stat().st_mtime)
    return latest


def runtime_status() -> dict[str, Any]:
    extension_path = package_extension_path()
    release_path = release_library_path()
    extension_mtime = extension_path.stat().st_mtime if extension_path.exists() else None
    release_mtime = release_path.stat().st_mtime if release_path.exists() else None
    source_mtime = latest_source_mtime()

    stale_reason = None
    if extension_mtime is None:
        stale_reason = "python extension missing"
    elif release_mtime is not None and extension_mtime + 1 < release_mtime:
        stale_reason = "python extension older than release library"
    elif extension_mtime + 1 < source_mtime:
        stale_reason = "python extension older than Rust source tree"
    elif release_mtime is None:
        stale_reason = "release library missing"

    return {
        "package_dir": str(PACKAGE_DIR),
        "extension_path": str(extension_path),
        "release_path": str(release_path),
        "extension_exists": extension_path.exists(),
        "release_exists": release_path.exists(),
        "extension_mtime": extension_mtime,
        "release_mtime": release_mtime,
        "source_mtime": source_mtime,
        "is_stale": stale_reason is not None,
        "stale_reason": stale_reason,
    }


def _cargo_build_release() -> None:
    subprocess.run(
        ["cargo", "build", "--release"],
        cwd=WORKOUT_PARSE_DIR,
        check=True,
    )


def _install_release_library() -> Path:
    release_path = release_library_path()
    if not release_path.exists():
        raise RuntimeError(f"Release library not found after build: {release_path}")

    extension_path = package_extension_path()
    extension_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(release_path, extension_path)
    if os.name != "nt":
        mode = extension_path.stat().st_mode
        extension_path.chmod(mode | 0o111)
    return extension_path


def ensure_workout_parse_fresh() -> dict[str, Any]:
    status = runtime_status()
    if not status["is_stale"]:
        return status

    _cargo_build_release()
    installed = _install_release_library()
    status = runtime_status()
    status["installed_path"] = str(installed)
    return status


def import_workout_parse_verified():
    ensure_workout_parse_fresh()

    package_parent = PACKAGE_DIR.parent
    if str(package_parent) not in sys.path:
        sys.path.insert(0, str(package_parent))

    if "workout_parse" in sys.modules:
        return importlib.reload(sys.modules["workout_parse"])
    return importlib.import_module("workout_parse")
