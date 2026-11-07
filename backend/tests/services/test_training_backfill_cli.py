import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest


@pytest.mark.asyncio
async def test_cli_cannot_select_a_ride_between_payment_phases(monkeypatch, capsys):
    spec = importlib.util.spec_from_file_location(
        "training_cli",
        Path(__file__).resolve().parents[2] / "scripts/backfill_training_metrics.py",
    )
    cli = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cli)
    candidates = [
        {
            "id": status,
            "processing_status": status,
            "phase3_completed_at": "2026-10-01T00:00:00Z",
            "phase1_completed_at": "2026-10-08T00:00:00Z",
        }
        for status in [
            "completed",
            "failed",
            "processing",
            "metrics_ready",
            "enriched",
            "under_review",
        ]
    ]
    candidates.append(
        {
            "id": "reviewed",
            "processing_status": "under_review",
            "phase3_completed_at": "2026-10-08T00:03:00Z",
            "phase1_completed_at": "2026-10-08T00:01:00Z",
            "phase2_completed_at": "2026-10-08T00:02:00Z",
        }
    )

    class Query:
        @property
        def not_(self):
            return self

        def __getattr__(self, name):
            def call(*args):
                return SimpleNamespace(data=candidates) if name == "execute" else self

            return call

    async def run(query):
        return query()

    repo = SimpleNamespace(client=Query(), _run=run)
    monkeypatch.setattr(cli, "get_supabase_client", lambda: None)
    monkeypatch.setattr(cli, "RideRepository", lambda _: repo)
    monkeypatch.setattr(cli, "FileStorageService", lambda _: None)
    monkeypatch.setattr(cli, "backfill_training", AsyncMock(return_value={"failed": 0, "skipped": 0}))
    await cli.main(SimpleNamespace(user_id="synthetic", apply=False, force=False, force_terminal=False))
    selected = cli.backfill_training.call_args.args[1]
    assert [r["id"] for r in selected] == ["completed", "reviewed"]
    assert cli.json.loads(capsys.readouterr().out)["skipped"] == 5
