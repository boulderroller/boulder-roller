from __future__ import annotations

from types import MethodType
from uuid import uuid4

import pytest

from app.repositories.user import UserRepository


@pytest.mark.asyncio
async def test_user_identifier_accepts_opaque_user_id_before_wallet_or_username() -> None:
    repo = UserRepository(client=None)  # type: ignore[arg-type]
    user_id = str(uuid4())
    calls: list[str] = []

    async def fake_get_user_by_id(self: UserRepository, lookup: str) -> dict[str, str]:
        calls.append(lookup)
        return {"id": lookup, "username": "rider", "wallet": "wallet-1"}

    repo.get_user_by_id = MethodType(fake_get_user_by_id, repo)  # type: ignore[method-assign]

    result = await repo.get_user_by_identifier(user_id)

    assert calls == [user_id]
    assert result == {"id": user_id, "username": "rider", "wallet": "wallet-1"}
