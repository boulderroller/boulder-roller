#!/usr/bin/env python3
"""
Friendly wrapper for the climb-review HTML report.

Examples:

  python3 scripts/review_climb.py t_h_e_w_a_l_l.fit
  python3 scripts/review_climb.py ~/Downloads/some_ride.fit --terrain rolling
  python3 scripts/review_climb.py 1d129d39-f2da-46c0-94d6-73726cb5b536 --terrain rolling
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Optional


REPO_ROOT = Path(__file__).resolve().parent.parent
VALIDATION_DIR = REPO_ROOT / "tests" / "validation"
RENDER_SCRIPT = VALIDATION_DIR / "render_climb_review.py"
BACKEND_ENV = REPO_ROOT / "backend" / ".env"
UUID_RE = re.compile(
    r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Open a visual climb review for a BR ride, validation file, or local file."
    )
    parser.add_argument(
        "target",
        help="Ride UUID, validation fixture name, or path to a local FIT/GPX/TCX file",
    )
    parser.add_argument(
        "--terrain",
        default=None,
        help="Optional terrain hint for the supporting sweep (rolling, hilly, urban_hills, etc.)",
    )
    parser.add_argument(
        "--sample-mode",
        default=None,
        choices=["raw", "tile-runs"],
        help="Optional detector sample mode override",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Optional HTML output path",
    )
    parser.add_argument(
        "--min-vert-m",
        type=float,
        default=None,
        help="Optional minimum climb vertical for shown rows",
    )
    parser.add_argument(
        "--no-open",
        action="store_true",
        help="Generate the report without opening it in the browser",
    )
    return parser.parse_args()


def load_env_file(env_path: Path) -> None:
    if not env_path.exists():
        return
    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[len("export ") :]
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue
        value = value.strip()
        if value and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ[key] = value


def load_manifest_filenames() -> list[str]:
    manifest_path = VALIDATION_DIR / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    return [entry["file"] for entry in manifest.get("files", []) if entry.get("file")]


def find_validation_match(target: str) -> Optional[str]:
    filenames = load_manifest_filenames()
    if target in filenames:
        return target

    target_stem = Path(target).stem
    exact_stem_matches = [name for name in filenames if Path(name).stem == target_stem]
    if len(exact_stem_matches) == 1:
        return exact_stem_matches[0]

    lower_target = target.lower()
    lower_matches = [name for name in filenames if name.lower() == lower_target]
    if len(lower_matches) == 1:
        return lower_matches[0]

    return None


def sanitize_label(label: str) -> str:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", label)
    return safe.strip("_") or "climb-review"


def default_output_path(label: str) -> Path:
    return Path("/tmp") / f"{sanitize_label(label)}.climb-review.html"


def detect_target(target: str) -> tuple[list[str], str, bool]:
    if UUID_RE.fullmatch(target):
        return ["--ride-id", target], target, True

    candidate_path = Path(target).expanduser()
    if candidate_path.exists():
        resolved = candidate_path.resolve()
        return ["--file", str(resolved)], resolved.name, False

    validation_match = find_validation_match(target)
    if validation_match:
        return ["--validation-file", validation_match], validation_match, False

    raise SystemExit(
        "Could not resolve target. Use a ride UUID, a local file path, or a validation fixture name."
    )


def build_command(args: argparse.Namespace) -> tuple[list[str], Path, bool]:
    target_args, label, needs_backend_env = detect_target(args.target)
    output_path = Path(args.output).expanduser().resolve() if args.output else default_output_path(label)

    command = [sys.executable, str(RENDER_SCRIPT), *target_args, "--output", str(output_path)]
    if args.terrain:
        command.extend(["--terrain", args.terrain])
    if args.sample_mode:
        command.extend(["--sample-mode", args.sample_mode])
    if args.min_vert_m is not None:
        command.extend(["--min-vert-m", str(args.min_vert_m)])
    return command, output_path, needs_backend_env


def extract_json_block(text: str) -> Optional[dict]:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None


def open_report(path: Path) -> None:
    opener: list[str]
    if sys.platform == "darwin":
        opener = ["open", str(path)]
    elif sys.platform.startswith("linux"):
        opener = ["xdg-open", str(path)]
    else:
        return
    subprocess.run(opener, check=False)


def main() -> int:
    args = parse_args()
    command, output_path, needs_backend_env = build_command(args)

    env = os.environ.copy()
    env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")
    if needs_backend_env:
        load_env_file(BACKEND_ENV)
        env = os.environ.copy()
        env.setdefault("MPLCONFIGDIR", "/tmp/matplotlib")

    completed = subprocess.run(
        command,
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
    )

    if completed.returncode != 0:
        if completed.stdout:
            print(completed.stdout.rstrip())
        if completed.stderr:
            print(completed.stderr.rstrip(), file=sys.stderr)
        return completed.returncode

    summary = extract_json_block(completed.stdout)
    if summary is None:
        print(completed.stdout.rstrip())
    else:
        print(f"Report ready: {summary['output']}")
        print(
            "Climbs shown: "
            f"persistence {summary['persistence_shown']}, "
            f"{summary['comparison_label']} {summary['comparison_shown']}, "
            f"suspicious persistence {summary['suspicious_persistence']}"
        )

    if not args.no_open:
        open_report(output_path)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
