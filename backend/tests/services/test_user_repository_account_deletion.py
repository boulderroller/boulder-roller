from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from app.repositories.user import UserRepository


def _repository(*responses: object) -> UserRepository:
    repository = UserRepository.__new__(UserRepository)
    repository._client = object()
    repository._run = AsyncMock(side_effect=responses)
    return repository


@pytest.mark.asyncio
async def test_auth_account_authority_is_one_combined_read() -> None:
    repository = _repository(
        SimpleNamespace(
            data=[
                {
                    "user_id": "user-1",
                    "account_state": "deletion_pending",
                }
            ]
        )
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": "user-1",
        "account_state": "deletion_pending",
    }
    assert repository._run.await_count == 1


@pytest.mark.asyncio
async def test_auth_account_authority_returns_missing_without_creating_state() -> None:
    repository = _repository(
        SimpleNamespace(data=[{"user_id": None, "account_state": None}]),
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": None,
        "account_state": None,
    }
    assert repository._run.await_count == 1


@pytest.mark.asyncio
async def test_auth_account_authority_gives_tombstone_precedence_over_a_user() -> None:
    repository = _repository(
        SimpleNamespace(data=[{"user_id": None, "account_state": "anonymized"}]),
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": None,
        "account_state": "anonymized",
    }


@pytest.mark.asyncio
async def test_auth_account_authority_fails_closed_after_bounded_transient_retries() -> None:
    repository = _repository(
        RuntimeError("connection timed out"),
        RuntimeError("connection timed out"),
    )

    with pytest.raises(RuntimeError, match="connection timed out"):
        await repository.get_auth_account_authority("wallet-1")
    assert repository._run.await_count == 2


@pytest.mark.asyncio
async def test_auth_account_authority_falls_back_only_when_lifecycle_column_is_missing() -> None:
    repository = _repository(
        RuntimeError("PGRST202 could not find function public.br_get_auth_account_authority"),
        SimpleNamespace(data=False),
        RuntimeError("column users.account_state does not exist"),
        SimpleNamespace(data=[{"id": "user-1"}]),
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": "user-1",
        "account_state": "active",
    }
    assert repository._run.await_count == 4


@pytest.mark.asyncio
@pytest.mark.parametrize("account_state", ["active", "deletion_pending"])
async def test_auth_account_authority_retries_one_transient_combined_read(
    account_state: str,
) -> None:
    repository = _repository(
        RuntimeError("database unavailable"),
        SimpleNamespace(data=[{"user_id": "user-1", "account_state": account_state}]),
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": "user-1",
        "account_state": account_state,
    }
    assert repository._run.await_count == 2


@pytest.mark.asyncio
async def test_auth_account_authority_does_not_hide_repeated_database_outages() -> None:
    repository = _repository(
        RuntimeError("database unavailable"),
        RuntimeError("database unavailable"),
    )

    with pytest.raises(RuntimeError, match="database unavailable"):
        await repository.get_auth_account_authority("wallet-1")


@pytest.mark.asyncio
async def test_new_wallet_survives_code_first_deploy_with_both_lifecycle_rpcs_missing() -> None:
    repository = _repository(
        RuntimeError("PGRST202 could not find function public.br_get_auth_account_authority"),
        RuntimeError("PGRST202 could not find function public.br_is_account_deleted"),
        SimpleNamespace(data=[]),
        RuntimeError("column users.account_state does not exist"),
        SimpleNamespace(data=[]),
        RuntimeError("PGRST202 could not find function public.br_get_or_create_active_user"),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[{}]),
    )

    assert await repository.get_auth_account_authority("wallet-1") == {
        "user_id": None,
        "account_state": None,
    }
    created_user_id = await repository.create_user("wallet-1")

    assert str(UUID(created_user_id)) == created_user_id
    assert repository._run.await_count == 9


@pytest.mark.asyncio
async def test_code_first_legacy_create_still_rejects_a_deleted_wallet() -> None:
    repository = _repository(
        RuntimeError("PGRST202 could not find function public.br_get_or_create_active_user"),
        SimpleNamespace(data=[{"wallet": "wallet-1"}]),
    )

    with pytest.raises(RuntimeError, match="account_deleted"):
        await repository.create_user("wallet-1")

    assert repository._run.await_count == 2
