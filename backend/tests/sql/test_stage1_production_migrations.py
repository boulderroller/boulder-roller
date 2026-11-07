"""Opt-in production-shaped migration rehearsal; exports never live in Git."""
import os
from pathlib import Path

import pytest


def test_whole_stage1_stack_on_exported_production_schema(monkeypatch):
    paths = [os.environ.get(name) for name in ("STAGE1_PROD_SCHEMA_FILE", "STAGE1_PROD_LEDGER_FILE")]
    if not all(path and Path(path).is_file() for path in paths):
        pytest.skip("Local schema and ledger exports absent; set STAGE1_PROD_SCHEMA_FILE/STAGE1_PROD_LEDGER_FILE")
    from scripts.rehearse_stage1_migrations import rehearse

    # Invalid libpq routing fails before connecting if the harness leaks the
    # caller's environment; these cannot route a failed test to a real server.
    monkeypatch.setenv("PGHOSTADDR", "not-a-numeric-address")
    monkeypatch.setenv("PGSERVICE", "nonexistent-stage1-rehearsal-service")
    result = rehearse(*(Path(path) for path in paths))
    assert result["rerun"] == "clean no-op; complete ledger unchanged"
    assert result["invariants"].startswith("Schema invariant check passed:")
    assert os.environ["PGHOSTADDR"] == "not-a-numeric-address"
