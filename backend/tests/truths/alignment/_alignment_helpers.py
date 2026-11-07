"""Helpers for PROTOCOL_TRUTHS_ALIGNMENT_GATE.

These helpers resolve absolute paths to the three TRUTHS docs and to the
mobile + backend source trees. Every test in this directory leans on these
primitives so paths are not scattered across the suite.

No runtime import of the application graph. Pure file-system + regex.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, List, Tuple


# ---------------------------------------------------------------------------
# Repository layout
# ---------------------------------------------------------------------------


def repo_root() -> Path:
    """Absolute path to the repository root.

    This file lives at ``backend/tests/truths/alignment/_alignment_helpers.py``
    so the repo root is four levels up.
    """
    return Path(__file__).resolve().parents[4]


def anchor_program_source() -> str:
    """The Anchor program's Rust source, joined across every module file."""
    src = repo_root() / "protocol" / "anchor" / "programs" / "boulder_rollers" / "src"
    return "\n".join(path.read_text(encoding="utf-8") for path in sorted(src.glob("*.rs")))


def docs_dir() -> Path:
    return repo_root() / "docs"


def mobile_src() -> Path:
    return repo_root() / "mobile" / "src"


def backend_app() -> Path:
    return repo_root() / "backend" / "app"


# ---------------------------------------------------------------------------
# TRUTHS doc readers
# ---------------------------------------------------------------------------


def read_truths(name: str) -> str:
    """Read one of the three TRUTHS markdown files by logical name.

    ``name`` ∈ {"protocol", "mobile", "backend"}. Raises ``FileNotFoundError``
    if the file has moved — that itself is a cross-lane drift signal.
    """
    mapping = {
        "protocol": "PROTOCOL_TRUTHS.md",
        "mobile": "MOBILE_TRUTHS.md",
        "backend": "BACKEND_TRUTHS.md",
    }
    if name not in mapping:
        raise ValueError(f"unknown TRUTHS doc: {name}")
    return (docs_dir() / mapping[name]).read_text(encoding="utf-8")


def read_file(relative_to_repo_root: str) -> str:
    """Read any repo file by path relative to the repo root."""
    return (repo_root() / relative_to_repo_root).read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Markdown section extraction
# ---------------------------------------------------------------------------


_SECTION_HEADER_RE = re.compile(
    r"^(?P<hashes>#{2,})\s+(?P<number>\d+(?:\.\d+)?)\.?\s+(?P<title>.*)$",
    re.MULTILINE,
)


def list_section_numbers(markdown: str) -> List[str]:
    """Return every ``§`` section number declared in a TRUTHS markdown doc.

    Matches headers of the form ``## 3`` or ``### 3.1``. Supports one level
    of dotted subsection (e.g., ``3.1``). Deeper nesting is not required
    because the TRUTHS docs author at most ``N.M`` depth.
    """
    out: List[str] = []
    for m in _SECTION_HEADER_RE.finditer(markdown):
        out.append(m.group("number"))
    return out


# ---------------------------------------------------------------------------
# §N citation extraction (for cross-doc link-rot scan)
# ---------------------------------------------------------------------------


_PROTOCOL_CITATION_RE = re.compile(
    r"PROTOCOL_TRUTHS\s*§\s*(?P<number>\d+(?:\.\d+)?)",
)


def find_protocol_citations(markdown: str) -> List[Tuple[int, str, str]]:
    """Return ``(lineno, section_number, surrounding_line)`` for every
    ``PROTOCOL_TRUTHS §N`` reference in a markdown doc.
    """
    out: List[Tuple[int, str, str]] = []
    lines = markdown.splitlines()
    for idx, line in enumerate(lines, start=1):
        for m in _PROTOCOL_CITATION_RE.finditer(line):
            out.append((idx, m.group("number"), line.strip()))
    return out


# ---------------------------------------------------------------------------
# Serialization / field-name scans (mobile + backend)
# ---------------------------------------------------------------------------


def grep_lines(text: str, pattern: str, flags: int = 0) -> List[Tuple[int, str]]:
    """Return ``(lineno, line)`` 1-indexed matches of ``pattern`` in ``text``."""
    compiled = re.compile(pattern, flags)
    out: List[Tuple[int, str]] = []
    for idx, line in enumerate(text.splitlines(), start=1):
        if compiled.search(line):
            out.append((idx, line))
    return out


def field_names_in_mobile_upload_payload() -> Dict[str, bool]:
    """Extract the field names mobile includes in the /rides/upload/init
    payload.

    Reads ``mobile/src/services/uploadQueue.ts`` and parses the
    ``buildUploadInitPayload`` body for snake_case keys written onto the
    ``payload`` object. Returns ``{field_name: always_present}`` where
    ``always_present`` is True for unconditional payload keys and False for
    keys wrapped in an ``if`` gate (optional).
    """
    source = (mobile_src() / "services" / "uploadQueue.ts").read_text(
        encoding="utf-8"
    )

    # Slice the buildUploadInitPayload function body. The signature itself
    # embeds `{ ... }` for the args object type, so the "function body"
    # open-brace is the one that appears AFTER the signature's closing
    # paren and return type. Balance parens first, then skip to ``): T {``
    # and take the next ``{`` as body start.
    start = source.find("export function buildUploadInitPayload")
    if start < 0:
        return {}
    # Find the '(' that opens the arg list, then balance parens.
    paren_start = source.find("(", start)
    depth = 1
    j = paren_start + 1
    while j < len(source) and depth > 0:
        ch = source[j]
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        j += 1
    # Now find the next `{` — that's the function body opener.
    open_brace = source.find("{", j)
    depth = 1
    i = open_brace + 1
    while i < len(source) and depth > 0:
        ch = source[i]
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
        i += 1
    body = source[open_brace + 1 : i - 1]

    fields: Dict[str, bool] = {}

    # Unconditional assignments inside the initial literal:
    #   file_type: ..., file_hash: ..., file_size: ...
    literal_match = re.search(
        r"const\s+payload\s*:\s*[^=]+=\s*\{([\s\S]*?)\}\s*;",
        body,
    )
    if literal_match:
        for key_match in re.finditer(r"(\w+)\s*:", literal_match.group(1)):
            fields[key_match.group(1)] = True

    # Conditional: payload.FIELD = ...
    for key_match in re.finditer(r"payload\.(\w+)\s*=", body):
        name = key_match.group(1)
        fields.setdefault(name, False)  # optional unless already unconditional

    return fields


def backend_upload_init_request_fields() -> List[str]:
    """Return the declared field names on the backend ``UploadInitRequest``
    Pydantic model.

    Reads ``backend/app/schemas.py`` and captures ``name: type`` declarations
    inside the ``class UploadInitRequest(BaseModel):`` block until the next
    top-level ``class`` / blank end-of-class.
    """
    source = (backend_app() / "schemas.py").read_text(encoding="utf-8")
    start_match = re.search(r"^class\s+UploadInitRequest\b[^\n]*:\s*$", source, re.MULTILINE)
    if not start_match:
        return []
    start = start_match.end()
    tail = source[start:]
    # Next top-level class / def ends the block.
    end_match = re.search(r"^(class|def)\s", tail, re.MULTILINE)
    end = len(source) if not end_match else start + end_match.start()
    body = source[start:end]

    fields: List[str] = []
    for m in re.finditer(
        r"^\s{4}(\w+)\s*:\s*[^\n=]+(?:=|$)",
        body,
        re.MULTILINE,
    ):
        name = m.group(1)
        if name in {"model_config"}:
            continue
        fields.append(name)
    return fields


def pydantic_extra_policy_for(class_name: str) -> str | None:
    """Return the ``extra=`` policy declared on the Pydantic model named
    ``class_name`` in schemas.py, if any.

    Returns one of ``"ignore" | "allow" | "forbid"``, or ``None`` if the
    class body doesn't pin an extra policy (Pydantic default is ``ignore``).
    """
    source = (backend_app() / "schemas.py").read_text(encoding="utf-8")
    start_match = re.search(
        rf"^class\s+{re.escape(class_name)}\b[^\n]*:\s*$", source, re.MULTILINE
    )
    if not start_match:
        return None
    start = start_match.end()
    tail = source[start:]
    end_match = re.search(r"^(class|def)\s", tail, re.MULTILINE)
    end = len(source) if not end_match else start + end_match.start()
    body = source[start:end]

    m = re.search(r"extra\s*=\s*['\"](ignore|allow|forbid)['\"]", body)
    return m.group(1) if m else None
