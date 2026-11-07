"""Climb-first public surface regression gate.

PROTOCOL_TRUTHS §11 makes ``Climb`` the canonical public object. ``Vault``
remains the optional economic wrapper, and ``segment`` survives only as a
temporary compatibility lane. This gate keeps that split from drifting back.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from ._alignment_helpers import read_file, repo_root


SEGMENT_COMPAT_MARKERS = (
    "back-compat",
    "compat",
    "legacy",
    "deprecated",
    "alias",
    "older",
    "existing clients",
    "rename",
    "not \"segment\"",
)

SEGMENT_SURFACE_FILES = (
    "backend/app/main.py",
    "backend/app/routes/climbs.py",
    "web/portal/src/lib/api.ts",
    "web/portal/src/lib/routePrefetch.ts",
    "web/scan/src/lib/search.ts",
    "web/scan/src/App.tsx",
)

LEGACY_ECONOMIC_COPY_RE = re.compile(
    r"\b(?:Synthetix|Merkle|epoch[-\s]+distribution)\b",
    re.IGNORECASE,
)

FRONTEND_COPY_DIRS = (
    "mobile/src/",
    "web/portal/src/",
    "web/scan/src/",
)

FRONTEND_COPY_SUFFIXES = {".ts", ".tsx"}


def _tracked_files() -> list[str]:
    result = subprocess.run(
        ["git", "ls-files"],
        cwd=repo_root(),
        check=True,
        capture_output=True,
        text=True,
    )
    return [line for line in result.stdout.splitlines() if line]


def _context(lines: list[str], line_number: int, radius: int = 3) -> str:
    start = max(0, line_number - radius - 1)
    end = min(len(lines), line_number + radius)
    return "\n".join(lines[start:end])


def _has_segment_compat_marker(context: str) -> bool:
    normalized = context.lower()
    return any(marker in normalized for marker in SEGMENT_COMPAT_MARKERS)


def test_backend_climb_router_is_canonical_and_segments_are_compat_only() -> None:
    """BACKEND_TRUTHS §12 / PROTOCOL_TRUTHS §11 - STATUS: PASS."""
    main_py = read_file("backend/app/main.py")
    climbs_py = read_file("backend/app/routes/climbs.py")

    assert 'app.include_router(climbs.router, prefix="/climbs")' in main_py, (
        "Backend must mount the canonical Climb router at /climbs."
    )

    assert 'app.include_router(climbs.router, prefix="/segments")' in main_py, (
        "The /segments compatibility mount disappeared. Remove this assertion "
        "only when the compatibility lane is deliberately retired."
    )

    lines = main_py.splitlines()
    segment_mount_line = next(
        idx
        for idx, line in enumerate(lines, start=1)
        if 'prefix="/segments"' in line
    )
    assert _has_segment_compat_marker(_context(lines, segment_mount_line)), (
        "The /segments mount must remain visibly marked as compatibility-only."
    )

    assert 'router = APIRouter(tags=["climbs"])' in climbs_py, (
        "OpenAPI tag for the canonical climb router must stay 'climbs', not "
        "'segments' or vault-first."
    )
    assert "@router.get(\"/list\"" in climbs_py, (
        "Canonical /climbs/list route must stay present for public clients."
    )
    assert "climbs: List[" in climbs_py, (
        "Climb list responses must expose the canonical 'climbs' key."
    )


def test_indexer_and_boulderscan_use_climb_route_with_vault_compatibility() -> None:
    """BoulderScan/indexer public read surface - STATUS: PASS."""
    indexer_api = read_file("indexer/src/api.ts")
    scan_api = read_file("web/scan/src/lib/api.ts")
    scan_app = read_file("web/scan/src/App.tsx")

    assert "v1\\/climbs" in indexer_api, (
        "Indexer must route canonical /v1/climbs endpoints."
    )
    assert "await handleClimbDetail(res, climbId)" in indexer_api, (
        "Canonical climb detail must resolve the immutable canon row UUID."
    )
    assert "await handleVaultDetail(res, vaultId)" in indexer_api, (
        "Numeric Vault detail must remain on the separate compatibility route."
    )
    assert "climbs: climbsResult.rows.map(serializeCanonClimbRow)" in indexer_api, (
        "/v1/climbs must expose canonical registry rows."
    )
    assert "total: parseCount(countResult.rows[0]?.total)" in indexer_api, (
        "/v1/climbs must preserve pagination totals and freshness metadata."
    )
    assert "climb: projectedClimb" in indexer_api, (
        "/v1/climbs/:id must expose the Climb as the primary object."
    )
    assert "vault: serializeVaultRow(vaultResult.rows[0])" in indexer_api, (
        "/v1/climbs/:id may attach its activated Vault as economy detail."
    )

    # Previously pinned readApi's raw id; ratified Climb uses an encoded canonical id and a live fetch.
    climb_reader = scan_api.split("export function getClimb(", 1)[1].split("export function getTransaction", 1)[0]
    assert 'const path = `/v1/climbs/${encodeURIComponent(id)}`' in climb_reader
    assert "fetchJson<ClimbResponse>(path)" in climb_reader
    assert "getVault" not in climb_reader
    assert "const legacy = await getVault(id)" not in scan_api, (
        "Canonical Climb detail must not silently fall back to numeric Vault identity."
    )
    assert '<Route path="/climb/:id"' in scan_app, (
        "BoulderScan must expose canonical /climb/:id pages."
    )
    assert '<Route path="/vault/:id"' in scan_app and "VaultRedirect" in scan_app, (
        "Legacy /vault/:id must redirect rather than remain the primary "
        "BoulderScan page."
    )


def test_mobile_uses_climb_route_with_vault_compatibility() -> None:
    """Mobile public read surface - STATUS: PASS."""
    mobile_api = read_file("mobile/src/lib/api.ts")
    tab_nav = read_file("mobile/src/navigation/TabNavigator.tsx")

    assert "async getClimbs(" in mobile_api, (
        "Mobile API client must expose canonical getClimbs()."
    )
    assert "this.request<ClimbListResponse>('GET', `/climbs/list?limit=${limit}`)" in mobile_api, (
        "Mobile getClimbs must call the canonical backend /climbs/list route."
    )
    assert "async getVaults(" in mobile_api and "return this.getClimbs(limit, offset)" in mobile_api, (
        "Mobile getVaults may exist only as a compatibility alias routed "
        "through getClimbs()."
    )
    assert 'name="Climbs"' in tab_nav and "ClimbsScreen" in tab_nav, (
        "Mobile tab navigation must expose Climbs as the primary rider surface."
    )


def test_segment_public_surface_occurrences_are_compat_marked() -> None:
    """Deprecated segment vocabulary outside explicit compatibility - STATUS: PASS."""
    pattern = re.compile(
        r"(/segments?\b|\bsegments\s*:|\bsegment_(?:id|name)\b)",
        re.IGNORECASE,
    )
    offenders: list[str] = []

    for relative_path in SEGMENT_SURFACE_FILES:
        text = read_file(relative_path)
        lines = text.splitlines()
        for idx, line in enumerate(lines, start=1):
            if not pattern.search(line):
                continue
            context = _context(lines, idx)
            if _has_segment_compat_marker(context):
                continue
            offenders.append(f"{relative_path}:{idx}: {line.strip()}")

    assert not offenders, (
        "Segment-era public surface names must be explicitly marked as "
        "compatibility-only. Rename the canonical surface to Climb or add a "
        "nearby legacy/back-compat marker:\n  "
        + "\n  ".join(offenders)
    )


def test_frontend_copy_avoids_retired_economic_jargon() -> None:
    """PROTOCOL_TRUTHS §11 copy discipline - STATUS: PASS."""
    offenders: list[str] = []

    for relative_path in _tracked_files():
        if not relative_path.startswith(FRONTEND_COPY_DIRS):
            continue
        if Path(relative_path).suffix not in FRONTEND_COPY_SUFFIXES:
            continue
        if "__tests__" in relative_path or relative_path.endswith(".test.ts"):
            continue

        path = repo_root() / relative_path
        if not path.exists():
            continue

        text = path.read_text(encoding="utf-8")
        for idx, line in enumerate(text.splitlines(), start=1):
            match = LEGACY_ECONOMIC_COPY_RE.search(line)
            if match:
                offenders.append(
                    f"{relative_path}:{idx}: retired term '{match.group(0)}' in `{line.strip()}`"
                )

    assert not offenders, (
        "Frontend copy must avoid old economic implementation jargon. Use "
        "Settlement Week, payout, Record Royalty, or Climb Vault terms "
        "instead:\n  "
        + "\n  ".join(offenders)
    )
