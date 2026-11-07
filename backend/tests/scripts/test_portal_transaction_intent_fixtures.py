from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path


BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = BACKEND_ROOT.parent
GENERATOR = BACKEND_ROOT / "scripts" / "generate_portal_transaction_intent_fixtures.py"
FIXTURE = (
    REPO_ROOT
    / "web"
    / "portal"
    / "scripts"
    / "fixtures"
    / "prepared-transaction-intents.json"
)


def test_portal_transaction_intent_fixture_matches_backend_builders() -> None:
    generated = subprocess.run(
        [sys.executable, str(GENERATOR)],
        cwd=BACKEND_ROOT,
        env={**os.environ, "PYTHONPATH": str(BACKEND_ROOT)},
        check=True,
        capture_output=True,
        text=True,
    )
    expected = json.loads(FIXTURE.read_text(encoding="utf-8"))
    actual = json.loads(generated.stdout)

    assert actual == expected
    assert len(actual) == 20
    assert {record["intent"]["kind"] for record in actual} == {
        "create_vault",
        "stake",
        "unstake",
        "balance_add_funds",
        "balance_withdraw",
    }
