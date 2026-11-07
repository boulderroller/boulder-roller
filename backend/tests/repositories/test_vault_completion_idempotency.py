from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.repositories.vault import VaultRepository


def _rpc_response(data):
    call = MagicMock()
    call.execute.return_value = SimpleNamespace(data=data)
    return call


def _builder(data):
    builder = MagicMock()
    builder.select.return_value = builder
    builder.eq.return_value = builder
    builder.limit.return_value = builder
    builder.upsert.return_value = builder
    builder.execute.return_value = SimpleNamespace(data=data)
    return builder


@pytest.mark.asyncio
async def test_record_completion_uses_atomic_projection_rpc() -> None:
    client = MagicMock()
    client.rpc.return_value = _rpc_response({
        "inserted": True,
        "completion": {
            "id": "completion-1",
            "vault_signature": "ab" * 64,
            "activity_id": "ride-1",
            "validated": True,
        },
    })
    repo = VaultRepository(client)

    result = await repo.record_completion(
        vault_signature="ab" * 64,
        wallet="Wallet111",
        activity_id="ride-1",
        time_seconds=812,
        completed_at=datetime(2026, 4, 21, 12, tzinfo=timezone.utc),
        validate_time=False,
    )

    assert result["_inserted"] is True
    assert result["activity_id"] == "ride-1"
    client.rpc.assert_called_once()
    assert client.rpc.call_args.args[0] == "record_vault_completion_projection"
    client.from_.assert_not_called()


@pytest.mark.asyncio
async def test_record_completion_fallback_does_not_increment_existing_projection() -> None:
    client = MagicMock()
    client.rpc.side_effect = RuntimeError("missing function")
    select_builder = _builder([{"id": "existing-completion"}])
    upsert_builder = _builder([{
        "id": "existing-completion",
        "vault_signature": "cd" * 64,
        "activity_id": "ride-2",
        "validated": True,
    }])
    client.from_.side_effect = [select_builder, upsert_builder]
    repo = VaultRepository(client)

    result = await repo.record_completion(
        vault_signature="cd" * 64,
        wallet="Wallet222",
        activity_id="ride-2",
        time_seconds=900,
        completed_at=datetime(2026, 4, 21, 13, tzinfo=timezone.utc),
        validate_time=False,
    )

    assert result["_inserted"] is False
    assert client.rpc.call_count == 1
    assert client.rpc.call_args.args[0] == "record_vault_completion_projection"


@pytest.mark.asyncio
async def test_record_completion_fallback_never_mutates_chain_owned_total() -> None:
    client = MagicMock()
    client.rpc.side_effect = RuntimeError("missing function")
    select_builder = _builder([])
    upsert_builder = _builder([{
        "id": "new-completion",
        "vault_signature": "ef" * 64,
        "activity_id": "ride-3",
        "validated": True,
    }])
    client.from_.side_effect = [select_builder, upsert_builder]
    repo = VaultRepository(client)

    result = await repo.record_completion(
        vault_signature="ef" * 64,
        wallet="Wallet333",
        activity_id="ride-3",
        time_seconds=780,
        completed_at=datetime(2026, 4, 21, 14, tzinfo=timezone.utc),
        validate_time=False,
    )

    assert result["_inserted"] is True
    client.rpc.assert_called_once()
    assert client.rpc.call_args.args[0] == "record_vault_completion_projection"
