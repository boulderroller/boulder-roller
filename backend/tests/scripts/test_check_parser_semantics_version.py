"""Executable pass/fail tests for the parser semantic-version CI gate."""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]
GATE = REPO_ROOT / "tools" / "check_parser_semantics_version.sh"


def _run(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        args, cwd=repo, check=check, capture_output=True, text=True
    )


def _write_sources(
    repo: Path,
    *,
    rust_current: str,
    ts_current: str,
    versions: set[int],
    version_values: dict[int, int] | None = None,
) -> None:
    version_values = version_values or {version: version for version in versions}
    rust = "\n".join(
        [
            f"pub const PARSER_VERSION_V{version}: u32 = {value};"
            for version, value in sorted(version_values.items())
        ]
        + [f"pub const CURRENT_PARSER_VERSION: u32 = {rust_current};", ""]
    )
    ts = "\n".join(
        [
            f"export const PARSER_VERSION_V{version} = {value};"
            for version, value in sorted(version_values.items())
        ]
        + [f"export const CURRENT_PARSER_VERSION = {ts_current};", ""]
    )
    (repo / "workout-parse/src").mkdir(parents=True, exist_ok=True)
    (repo / "mobile/src/lib").mkdir(parents=True, exist_ok=True)
    (repo / "workout-parse/src/canonicalize.rs").write_text(rust, encoding="utf-8")
    (repo / "mobile/src/lib/canonicalize.ts").write_text(ts, encoding="utf-8")


def _commit(repo: Path, message: str) -> str:
    _run(repo, "git", "add", ".")
    _run(repo, "git", "commit", "-m", message)
    return _run(repo, "git", "rev-parse", "HEAD").stdout.strip()


def _repo(tmp_path: Path) -> tuple[Path, str]:
    repo = tmp_path / "parser-gate"
    repo.mkdir()
    _run(repo, "git", "init")
    _run(repo, "git", "config", "user.email", "gate@example.test")
    _run(repo, "git", "config", "user.name", "Parser Gate")
    _write_sources(repo, rust_current="1", ts_current="1", versions={1})
    (repo / "tests/fixtures").mkdir(parents=True)
    (repo / "tests/fixtures/canonical_ride_v1_vectors.json").write_text(
        json.dumps({"parser_version": 1}), encoding="utf-8"
    )
    return repo, _commit(repo, "base")


def _add_v2(repo: Path, *, rust_current: str = "PARSER_VERSION_V2", ts_current: str = "PARSER_VERSION_V2") -> None:
    _write_sources(repo, rust_current=rust_current, ts_current=ts_current, versions={1, 2})
    (repo / "tests/fixtures/canonical_ride_v2_vectors.json").write_text(
        json.dumps({"parser_version": 2}), encoding="utf-8"
    )


def test_parser_semantic_gate_accepts_a_matched_version_bump(tmp_path: Path) -> None:
    repo, base = _repo(tmp_path)
    _add_v2(repo)
    _commit(repo, "v2")

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode == 0, result.stderr


def test_parser_semantic_gate_falls_back_to_canonical_branch_base(
    tmp_path: Path,
) -> None:
    repo, base = _repo(tmp_path)
    _run(repo, "git", "branch", "canonical-main", base)
    _add_v2(repo)
    _commit(repo, "v2")

    result = _run(
        repo,
        "env",
        "PARSER_SEMANTICS_FALLBACK_REF=canonical-main",
        "bash",
        str(GATE),
        "missing-force-push-base",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert "using canonical-main" in result.stderr


def test_parser_semantic_gate_fails_closed_without_a_comparison_base(
    tmp_path: Path,
) -> None:
    repo, _ = _repo(tmp_path)
    _add_v2(repo)
    _commit(repo, "v2")

    result = _run(
        repo,
        "env",
        "PARSER_SEMANTICS_FALLBACK_REF=missing-canonical-base",
        "bash",
        str(GATE),
        "missing-force-push-base",
        check=False,
    )
    assert result.returncode != 0
    assert "cannot resolve parser semantic comparison base" in result.stderr


@pytest.mark.parametrize(
    ("name", "mutate", "expected"),
    [
        (
            "unused_future_constant",
            lambda repo: _write_sources(
                repo, rust_current="PARSER_VERSION_V1", ts_current="PARSER_VERSION_V1", versions={1, 99}
            ),
            "must increase",
        ),
        (
            "cross_language_mismatch",
            lambda repo: _add_v2(repo, ts_current="3"),
            "same new integer",
        ),
        (
            "current_aliases_unused_v99",
            lambda repo: (
                _write_sources(
                    repo,
                    rust_current="PARSER_VERSION_V99",
                    ts_current="PARSER_VERSION_V99",
                    versions={1, 2, 99},
                    version_values={1: 1, 2: 2, 99: 2},
                ),
                (repo / "tests/fixtures/canonical_ride_v2_vectors.json").write_text(
                    json.dumps({"parser_version": 2}), encoding="utf-8"
                ),
            ),
            "must alias PARSER_VERSION_V2",
        ),
        (
            "missing_exact_vector",
            lambda repo: _write_sources(
                repo, rust_current="PARSER_VERSION_V2", ts_current="PARSER_VERSION_V2", versions={1, 2}
            ),
            "canonical_ride_v2_vectors.json",
        ),
    ],
)
def test_parser_semantic_gate_rejects_bypasses(
    tmp_path: Path, name: str, mutate, expected: str
) -> None:
    repo, base = _repo(tmp_path)
    mutate(repo)
    _commit(repo, name)

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode != 0
    assert expected in result.stderr


DECLARATION = (
    "Register a Python binding\n\n"
    "Parser-Semantics: unchanged\n"
    "  Only Python module registration and device evidence changed."
)


def _verification_tools(repo: Path, monkeypatch, *, rust: int = 0, mobile: int = 0) -> Path:
    """Stub tool outcomes for gate routing; real vector checks run separately."""
    bin_dir = repo / "fake-bin"
    bin_dir.mkdir()
    log = repo / "verification.log"
    for tool, status in [("python3", rust), ("npm", mobile)]:
        executable = bin_dir / tool
        executable.write_text(
            f'#!/bin/sh\nprintf "%s\\n" "{tool} $*" >> "$VERIFY_LOG"\nexit {status}\n',
            encoding="utf-8",
        )
        executable.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("VERIFY_LOG", str(log))
    return log


def _semantic_edit(repo: Path, language: str) -> None:
    if language in ("rust", "both"):
        (repo / "workout-parse/src/lib.rs").write_text("// Python binding registration\n")
    if language in ("mobile", "both"):
        with (repo / "mobile/src/lib/canonicalize.ts").open("a") as source:
            source.write("// Clarify an existing comment.\n")


@pytest.mark.parametrize("language", ["rust", "mobile", "both"])
def test_declared_and_verified_changes_pass(tmp_path: Path, monkeypatch, language: str) -> None:
    repo, base = _repo(tmp_path)
    _semantic_edit(repo, language)
    _commit(repo, DECLARATION)
    log = _verification_tools(repo, monkeypatch)

    result = _run(repo, "bash", str(GATE), base, check=False)

    assert result.returncode == 0, result.stderr
    assert "verified unchanged parser semantics" in result.stdout
    calls = log.read_text()
    assert ("verify_parser_semantics.py 1" in calls) == (language in ("rust", "both"))
    assert ("src/lib/__tests__/canonicalize.test.ts" in calls) == (language in ("mobile", "both"))


@pytest.mark.parametrize(("rust", "mobile"), [(1, 0), (0, 1), (127, 0), (0, 127)])
def test_declared_changes_fail_when_verification_fails_or_is_unavailable(
    tmp_path: Path, monkeypatch, rust: int, mobile: int
) -> None:
    repo, base = _repo(tmp_path)
    _semantic_edit(repo, "both")
    _commit(repo, DECLARATION)
    _verification_tools(repo, monkeypatch, rust=rust, mobile=mobile)

    result = _run(repo, "bash", str(GATE), base, check=False)

    assert result.returncode != 0
    assert "verification failed or unavailable" in result.stderr
    assert "must increase" in result.stderr


@pytest.mark.parametrize("message", [
    "No declaration",
    "No reason\n\nParser-Semantics: unchanged",
    "Wrong declaration\n\nParser-Semantics: changed\n  Binding registration.",
    "Quoted prose\n\nParser-Semantics: unchanged\n  Binding registration.\n\nNot a trailer.",
])
def test_undeclared_changes_still_require_a_bump(tmp_path: Path, monkeypatch, message: str) -> None:
    repo, base = _repo(tmp_path)
    _semantic_edit(repo, "rust")
    _commit(repo, message)
    log = _verification_tools(repo, monkeypatch)

    result = _run(repo, "bash", str(GATE), base, check=False)

    assert result.returncode != 0
    assert "must increase" in result.stderr
    assert not log.exists()


def test_declaration_can_be_in_an_empty_non_tip_commit(tmp_path: Path, monkeypatch) -> None:
    repo, base = _repo(tmp_path)
    _run(repo, "git", "commit", "--allow-empty", "-m", DECLARATION)
    _semantic_edit(repo, "rust")
    _commit(repo, "Register binding")
    _verification_tools(repo, monkeypatch)

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode == 0, result.stderr


def test_declaration_at_the_base_is_not_in_range(tmp_path: Path, monkeypatch) -> None:
    repo, _ = _repo(tmp_path)
    _run(repo, "git", "commit", "--allow-empty", "-m", DECLARATION)
    base = _run(repo, "git", "rev-parse", "HEAD").stdout.strip()
    _semantic_edit(repo, "rust")
    _commit(repo, "Register binding")
    log = _verification_tools(repo, monkeypatch)

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode != 0
    assert not log.exists()


@pytest.mark.parametrize("dirty", [False, True])
def test_exemption_cannot_rewrite_vectors_or_verify_uncommitted_code(
    tmp_path: Path, monkeypatch, dirty: bool
) -> None:
    repo, base = _repo(tmp_path)
    _semantic_edit(repo, "rust")
    if not dirty:
        (repo / "tests/fixtures/canonical_ride_v1_vectors.json").write_text("{}")
    _commit(repo, DECLARATION)
    if dirty:
        (repo / "workout-parse/src/lib.rs").write_text("// Uncommitted replacement\n")
    log = _verification_tools(repo, monkeypatch)

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode != 0
    assert "must increase" in result.stderr
    assert not log.exists()


def test_declared_real_bump_uses_existing_rules_without_verification(tmp_path: Path, monkeypatch) -> None:
    repo, base = _repo(tmp_path)
    _add_v2(repo)
    _commit(repo, DECLARATION)
    log = _verification_tools(repo, monkeypatch, rust=127, mobile=127)

    result = _run(repo, "bash", str(GATE), base, check=False)
    assert result.returncode == 0, result.stderr
    assert not log.exists()
