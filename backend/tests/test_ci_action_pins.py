"""Third-party GitHub Actions run beside repository secrets, and Backend CI's
deploy step holds the droplet's root key, so every action outside the
first-party actions/* namespace is pinned to an immutable commit (or image
digest) rather than a branch or tag its upstream can move."""

from __future__ import annotations

import re
from pathlib import Path

WORKFLOWS = Path(__file__).resolve().parents[2] / ".github" / "workflows"
USES = re.compile(r"^\s*(?:-\s+)?uses:\s*['\"]?([^\s'\"#]+)", re.MULTILINE)
PINNED = re.compile(r"@[0-9a-f]{40}$|^docker://.+@sha256:[0-9a-f]{64}$")


def test_third_party_actions_are_pinned_to_commit_shas() -> None:
    workflows = sorted([*WORKFLOWS.glob("*.yml"), *WORKFLOWS.glob("*.yaml")])
    assert workflows, f"no workflows found under {WORKFLOWS}"

    unpinned = [
        f"{path.name}: {action}"
        for path in workflows
        for action in USES.findall(path.read_text(encoding="utf-8"))
        if not action.startswith(("actions/", "./")) and not PINNED.search(action)
    ]

    assert unpinned == []
