from __future__ import annotations

import subprocess
from pathlib import Path

import pytest


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
GUARD = REPOSITORY_ROOT / "scripts" / "hooks" / "h3-resolution-guard.sh"
NONCANONICAL_SOURCE_LINES = [
    *("".join(("tile = h3.", "latlng_to_cell(lat, lon, ", str(value), ")\n"))
      for value in (7, 16)),
    *("".join(("let value = h3o::", "Resolution::try_from(", str(value), ")?;\n"))
      for value in (7, 16)),
]


def _repository(path: Path) -> Path:
    path.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    return path


def _run_guard(repository: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", str(GUARD)],
        cwd=repository,
        check=False,
        capture_output=True,
        text=True,
    )


def test_h3_guard_ignores_tracker_prose_that_cannot_change_tile_data(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path / "tracker")
    tracker = repository / ".beads" / "issues.jsonl"
    tracker.parent.mkdir()
    ordinary_word = "res" + "olution"
    unrelated_number = str(15)
    tracker.write_text(
        '{"text":"human ' + ordinary_word + ' = ' + unrelated_number + '"}\n',
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(tracker)], cwd=repository, check=True)

    result = _run_guard(repository)

    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("resolution", [7, 9, 16])
def test_h3_guard_still_rejects_every_noncanonical_numeric_resolution(
    tmp_path: Path,
    resolution: int,
) -> None:
    repository = _repository(tmp_path / "code")
    source = repository / "tiles.py"
    source.write_text(
        "H3_" + "RESOLUTION = " + str(resolution) + "\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(source)], cwd=repository, check=True)

    result = _run_guard(repository)

    assert result.returncode != 0
    assert "H3 RESOLUTION CHANGE DETECTED" in result.stdout


@pytest.mark.parametrize(
    "source_line",
    NONCANONICAL_SOURCE_LINES,
)
def test_h3_guard_rejects_noncanonical_call_and_h3o_literals(
    tmp_path: Path,
    source_line: str,
) -> None:
    repository = _repository(tmp_path / "code-call")
    source = repository / "tiles.rs"
    source.write_text(source_line, encoding="utf-8")
    subprocess.run(["git", "add", str(source)], cwd=repository, check=True)

    result = _run_guard(repository)

    assert result.returncode != 0
    assert "H3 RESOLUTION CHANGE DETECTED" in result.stdout


def test_h3_guard_allows_the_canonical_v4_call_literal(tmp_path: Path) -> None:
    repository = _repository(tmp_path / "canonical-call")
    source = repository / "tiles.py"
    source.write_text(
        "tile = h3.latlng_to_cell(lat, lon, 10)\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "add", str(source)], cwd=repository, check=True)

    result = _run_guard(repository)

    assert result.returncode == 0, result.stdout + result.stderr
