from __future__ import annotations

from uuid import uuid4

import pytest

from app.dependencies import AuthenticatedUser
from app.routes import users
from app.routes.users import list_sessions, revoke_all_other_sessions


class FakeAuthRepository:
    def __init__(self) -> None:
        self.current_session_id = str(uuid4())
        self.other_session_id = str(uuid4())
        self.list_hashes: list[str | None] = []
        self.revoked: list[str] = []

    async def list_user_sessions(
        self,
        wallet: str,
        current_token_hash: str | None,
        current_device_id: str | None = None,
    ) -> list[dict]:
        self.list_hashes.append(current_token_hash)
        return [
            {
                "id": self.current_session_id,
                "device_id": "cookie-device",
                "user_agent": "Safari",
                "created_at": "2026-05-14T10:00:00+00:00",
                "last_used_at": "2026-05-14T10:05:00+00:00",
                "token_hash": "stored-current",
            },
            {
                "id": self.other_session_id,
                "device_id": "other-device",
                "user_agent": "Chrome",
                "created_at": "2026-05-13T10:00:00+00:00",
                "last_used_at": "2026-05-13T10:05:00+00:00",
                "token_hash": "stored-other",
            },
        ]

    async def revoke_session_with_reason(self, session_id: str, wallet: str, reason: str) -> dict | None:
        self.revoked.append(session_id)
        return {"id": session_id, "device_id": "other-device", "wallet": wallet, "revocation_reason": reason}


class FakeNotificationService:
    async def notify_session_revoked(self, **kwargs: object) -> None:
        return None


@pytest.mark.asyncio
async def test_cookie_restored_session_list_marks_current_by_device(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeAuthRepository()
    monkeypatch.setattr(users, "create_auth_repository", lambda: repo)

    response = await list_sessions(
        current_user=AuthenticatedUser(
            wallet="wallet-1",
            user_id="user-1",
            device_id="cookie-device",
        ),
    )

    assert repo.list_hashes == [None]
    assert [session.is_current for session in response.sessions] == [True, False]


@pytest.mark.asyncio
async def test_cookie_restored_revoke_all_keeps_current_device(monkeypatch: pytest.MonkeyPatch) -> None:
    repo = FakeAuthRepository()
    monkeypatch.setattr(users, "create_auth_repository", lambda: repo)
    monkeypatch.setattr(users, "create_notification_service", lambda: FakeNotificationService())

    response = await revoke_all_other_sessions(
        current_user=AuthenticatedUser(
            wallet="wallet-1",
            user_id="user-1",
            device_id="cookie-device",
        ),
    )

    assert response.status == "revoked"
    assert response.count == 1
    assert repo.revoked == [repo.other_session_id]
