from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.repositories.auth import AuthRepository


class _FakeResponse:
    def __init__(self, data=None) -> None:
        self.data = data or []


class _LegacyDeviceIndexTable:
    def __init__(self) -> None:
        self.operations: list[tuple[str, dict, list[tuple[str, str, str]]]] = []
        self._operation = ""
        self._payload: dict = {}
        self._filters: list[tuple[str, str, str]] = []

    def insert(self, payload: dict):
        self._operation = "insert"
        self._payload = payload
        self._filters = []
        return self

    def update(self, payload: dict):
        self._operation = "update"
        self._payload = payload
        self._filters = []
        return self

    def eq(self, key: str, value: str):
        self._filters.append(("eq", key, value))
        return self

    def is_(self, key: str, value: str):
        self._filters.append(("is", key, value))
        return self

    def execute(self):
        self.operations.append((self._operation, self._payload.copy(), list(self._filters)))
        if self._operation == "insert":
            raise Exception(
                'duplicate key value violates unique constraint '
                '"idx_auth_refresh_unique_device"'
            )
        return _FakeResponse([self._payload])


class _FakeClient:
    def __init__(self, table: _LegacyDeviceIndexTable) -> None:
        self._table = table

    def table(self, name: str):
        assert name == "auth_refresh_tokens"
        return self._table


class _InlineAuthRepository(AuthRepository):
    async def _run(self, func, operation: str = "supabase"):
        return func()


def test_store_refresh_token_falls_back_when_legacy_device_index_exists() -> None:
    table = _LegacyDeviceIndexTable()
    repo = _InlineAuthRepository(_FakeClient(table))

    asyncio.run(
        repo.store_refresh_token(
            wallet="wallet-1",
            device_id="device-1",
            token_hash="token-hash-2",
            expires_at=datetime.now(timezone.utc) + timedelta(days=7),
            user_agent="pytest",
        )
    )

    assert [op[0] for op in table.operations] == ["update", "insert", "update"]

    revoke_op = table.operations[0]
    assert revoke_op[1]["revocation_reason"] == "replaced"

    insert_op = table.operations[1]
    assert insert_op[1]["wallet"] == "wallet-1"
    assert insert_op[1]["device_id"] == "device-1"
    assert insert_op[1]["token_hash"] == "token-hash-2"

    fallback_op = table.operations[2]
    assert fallback_op[1]["wallet"] == "wallet-1"
    assert fallback_op[1]["device_id"] == "device-1"
    assert fallback_op[1]["token_hash"] == "token-hash-2"
    assert fallback_op[1]["revoked_at"] is None
    assert fallback_op[1]["revocation_reason"] is None
    assert ("eq", "wallet", "wallet-1") in fallback_op[2]
    assert ("eq", "device_id", "device-1") in fallback_op[2]


def _mock_repository(*responses: object) -> AuthRepository:
    repository = AuthRepository.__new__(AuthRepository)
    repository._client = object()
    repository._run = AsyncMock(side_effect=responses)
    return repository


@pytest.mark.asyncio
async def test_nonce_issue_falls_back_only_when_the_lifecycle_rpc_is_missing() -> None:
    issued_at = datetime.now(timezone.utc)
    expires_at = issued_at + timedelta(minutes=5)
    repository = _mock_repository(
        RuntimeError("PGRST202 could not find function public.br_issue_auth_nonce"),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[{"id": "nonce-1", "wallet": "wallet-1", "nonce": "n-1"}]),
    )

    row = await repository.save_nonce(
        "wallet-1",
        "n-1",
        issued_at,
        expires_at,
        "device-1",
    )

    assert row["nonce"] == "n-1"
    assert repository._run.await_count == 3


@pytest.mark.asyncio
async def test_legacy_nonce_issue_still_rejects_a_deleted_wallet() -> None:
    issued_at = datetime.now(timezone.utc)
    repository = _mock_repository(
        RuntimeError("PGRST202 could not find function public.br_issue_auth_nonce"),
        SimpleNamespace(data=[{"wallet": "wallet-1"}]),
    )

    with pytest.raises(RuntimeError, match="account_deleted"):
        await repository.save_nonce(
            "wallet-1",
            "n-1",
            issued_at,
            issued_at + timedelta(minutes=5),
            "device-1",
        )
    assert repository._run.await_count == 2


@pytest.mark.asyncio
async def test_nonce_consume_falls_back_to_one_conditional_legacy_update() -> None:
    repository = _mock_repository(
        RuntimeError("PGRST202 could not find function public.br_consume_auth_nonce"),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[{"id": "nonce-1"}]),
    )

    assert await repository.consume_nonce(uuid.uuid4(), "wallet-1") is True
    assert repository._run.await_count == 3


@pytest.mark.asyncio
async def test_legacy_nonce_consume_rejects_a_deleted_wallet() -> None:
    repository = _mock_repository(
        RuntimeError("PGRST202 could not find function public.br_consume_auth_nonce"),
        SimpleNamespace(data=[{"wallet": "wallet-1"}]),
    )

    with pytest.raises(RuntimeError, match="account_deleted"):
        await repository.consume_nonce(uuid.uuid4(), "wallet-1")
    assert repository._run.await_count == 2


@pytest.mark.asyncio
async def test_nonce_rpc_fallback_does_not_hide_unrelated_failures() -> None:
    repository = _mock_repository(RuntimeError("database unavailable"))
    issued_at = datetime.now(timezone.utc)

    with pytest.raises(RuntimeError, match="database unavailable"):
        await repository.save_nonce(
            "wallet-1",
            "n-1",
            issued_at,
            issued_at + timedelta(minutes=5),
            "device-1",
        )
    assert repository._run.await_count == 1
