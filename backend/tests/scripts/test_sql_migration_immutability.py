from __future__ import annotations

import hashlib
from pathlib import Path

from backend.scripts.check_sql_migration_immutability import (
    RETIRED_ROOT_MIGRATION_CHECKSUMS,
    validate_retired_root_migrations,
)


ROOT = Path(__file__).resolve().parents[3]


def test_retired_root_migration_allowlist_locks_names_and_bytes() -> None:
    retired = ROOT / "supabase" / "migrations"
    actual = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in retired.glob("*.sql")
    }
    assert actual == RETIRED_ROOT_MIGRATION_CHECKSUMS
    validate_retired_root_migrations(retired)


def test_backend_ci_cannot_skip_retired_root_migration_guard() -> None:
    workflow = (ROOT / ".github" / "workflows" / "backend-ci.yml").read_text(
        encoding="utf-8"
    )

    # Both push and pull_request path filters must admit changes to the retired
    # root migration surface, or the checksum guard below could be bypassed.
    assert workflow.count("- 'supabase/migrations/**'") == 2
    assert workflow.count("- 'supabase/README.md'") == 2
    # Swift copy changes must exercise the cross-client parity test as well.
    push = workflow.split("\n  push:\n", 1)[1].split("\n  pull_request:\n", 1)[0]
    pull_request = workflow.split("\n  pull_request:\n", 1)[1].split("\n\n", 1)[0]
    for event in [push, pull_request]:
        assert "- 'ios/BoulderRoller/Design/EstimateCopy.swift'" in event
    assert "run: python scripts/check_sql_migration_immutability.py" in workflow
