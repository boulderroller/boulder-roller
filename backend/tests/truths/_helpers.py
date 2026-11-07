"""Static-scan helpers shared across BACKEND_TRUTHS Gate 1 tests.

These helpers parse backend source files with the `ast` module (no runtime
import of the application graph) so Gate 1 can run without a live Solana/FastAPI
environment. That is deliberate: the gate must be cheap enough to run in CI
before integration tests warm up, and must surface drift in source even when
the full app refuses to boot.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Repo locations
# ---------------------------------------------------------------------------


def backend_root() -> Path:
    """Absolute path to the backend package directory.

    This test file lives at `backend/tests/truths/_helpers.py`, so the backend
    package root (`backend/app`) is three levels up plus an `app` hop.
    """
    return Path(__file__).resolve().parents[2] / "app"


def repo_root() -> Path:
    """Absolute path to the repository root (contains the `backend/` dir)."""
    return Path(__file__).resolve().parents[3]


def read_source(relative_path: str) -> str:
    """Read a file inside `backend/app/` by path relative to that directory."""
    path = backend_root() / relative_path
    return path.read_text(encoding="utf-8")


def read_module_tree(relative_path: str) -> ast.Module:
    """Parse a file inside `backend/app/` to an AST module."""
    path = backend_root() / relative_path
    source = path.read_text(encoding="utf-8")
    return ast.parse(source, filename=str(path))


# ---------------------------------------------------------------------------
# AST call extraction
# ---------------------------------------------------------------------------


@dataclass
class CallSite:
    """A single function-call site discovered in a module tree."""

    func_name: str
    lineno: int
    col_offset: int
    keywords: Dict[str, ast.expr] = field(default_factory=dict)
    positional_args: List[ast.expr] = field(default_factory=list)
    is_await: bool = False

    def has_kwarg(self, name: str) -> bool:
        return name in self.keywords

    def kwarg(self, name: str) -> Optional[ast.expr]:
        return self.keywords.get(name)


def _callable_name(node: ast.expr) -> Optional[str]:
    """Best-effort extraction of a call target's simple name.

    Supports `foo(...)`, `pkg.foo(...)`, `self.foo(...)`, `obj.attr.foo(...)`.
    Returns the rightmost attribute / name (the function being invoked), which
    is what Gate 1 scans for.
    """
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def iter_calls(tree: ast.AST, names: Iterable[str]) -> Iterator[CallSite]:
    """Yield all CallSite objects in ``tree`` whose invoked name is in ``names``.

    Walks the whole subtree, so it catches calls inside nested functions /
    comprehensions. The caller is responsible for filtering false positives if
    a name is overloaded.
    """
    wanted: Set[str] = set(names)
    for node in ast.walk(tree):
        call_node: Optional[ast.Call] = None
        is_await = False

        if isinstance(node, ast.Call):
            call_node = node
        elif isinstance(node, ast.Await) and isinstance(node.value, ast.Call):
            call_node = node.value
            is_await = True
        else:
            continue

        name = _callable_name(call_node.func)
        if name not in wanted:
            continue

        keywords: Dict[str, ast.expr] = {}
        for kw in call_node.keywords:
            if kw.arg is not None:  # skip **kwargs
                keywords[kw.arg] = kw.value

        yield CallSite(
            func_name=name,
            lineno=call_node.lineno,
            col_offset=call_node.col_offset,
            keywords=keywords,
            positional_args=list(call_node.args),
            is_await=is_await,
        )


def call_sites(module: str, names: Iterable[str]) -> List[CallSite]:
    """Return call sites for ``names`` inside a backend module file."""
    tree = read_module_tree(module)
    return list(iter_calls(tree, names))


# ---------------------------------------------------------------------------
# Expression classification helpers
# ---------------------------------------------------------------------------


_WALL_CLOCK_NAMES: Set[Tuple[str, ...]] = {
    ("datetime", "utcnow"),
    ("datetime", "now"),
    ("time", "time"),
    ("time", "time_ns"),
    ("time", "monotonic"),
}


def is_wall_clock_call(node: ast.expr) -> bool:
    """True if ``node`` is a `datetime.utcnow()`, `time.time()`, etc. call.

    These are ambient-time expressions that must NEVER flow into the on-chain
    `completed_at` argument of `send_record_ride` (BACKEND_TRUTHS §3.1).
    """
    if not isinstance(node, ast.Call):
        return False

    func = node.func
    # `time.time()`, `datetime.utcnow()`
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Name):
        key = (func.value.id, func.attr)
        if key in _WALL_CLOCK_NAMES:
            return True
    # `datetime.datetime.utcnow()` (dotted)
    if isinstance(func, ast.Attribute) and isinstance(func.value, ast.Attribute):
        if isinstance(func.value.value, ast.Name):
            key = (func.value.attr, func.attr)
            if key in _WALL_CLOCK_NAMES:
                return True
    return False


def refers_to_file_time(node: ast.expr) -> bool:
    """True if ``node`` clearly sources from a parsed-ride timestamp.

    Permissive on purpose: we want to distinguish "came from the file" from
    "came from ambient clock". Any expression that references ``parsed_ride``
    / ``ride_start`` / ``completed_at`` (as attribute or name) is treated as
    file-sourced.
    """
    for sub in ast.walk(node):
        if isinstance(sub, ast.Attribute):
            if sub.attr in {"completed_at", "started_at", "start_time", "end_time"}:
                return True
        if isinstance(sub, ast.Name):
            if sub.id in {
                "completed_at",
                "ride_start_time",
                "ride_end_time",
                "ride_event_time",
                "parsed_ride",
            }:
                return True
    return False


# ---------------------------------------------------------------------------
# Source-line regex scans (for cases where AST is overkill)
# ---------------------------------------------------------------------------


def grep_source(
    relative_path: str,
    pattern: str,
    flags: int = 0,
) -> List[Tuple[int, str]]:
    """Return `(lineno, line)` tuples where ``pattern`` matches.

    Line numbers are 1-indexed. Use for shallow checks (naming, docstring
    drift) where AST parsing is overkill.
    """
    compiled = re.compile(pattern, flags)
    out: List[Tuple[int, str]] = []
    text = read_source(relative_path)
    for idx, line in enumerate(text.splitlines(), start=1):
        if compiled.search(line):
            out.append((idx, line))
    return out


def line_has_backcompat_marker(line: str) -> bool:
    """True if ``line`` carries a conventional back-compat allowlist marker.

    Tests use this to whitelist intentional legacy surface (a field named
    ``segments:`` that must stay for API stability).
    """
    lowered = line.lower()
    return any(
        marker in lowered
        for marker in (
            "back-compat",
            "backcompat",
            "compat alias",
            "legacy alias",
            "legacy_router",
            "# segments:",
            "segment-era",
        )
    )
