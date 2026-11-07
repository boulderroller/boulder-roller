from unittest.mock import AsyncMock
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

from app.dependencies import AuthenticatedUser, get_optional_current_user_strict, get_repository
from app.routes.social import router


OWNER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"


@pytest.mark.parametrize("list_name", ["followers", "following"])
@pytest.mark.parametrize("viewer", [None, OTHER, OWNER])
@pytest.mark.parametrize("public", [False, True])
def test_social_lists_follow_target_profile_visibility(list_name, viewer, public):
    repo = SimpleNamespace(
        get_user_by_id=AsyncMock(return_value={"id": OWNER, "is_public": public}),
        # A follower still cannot view a private profile's lists.
        get_follow=AsyncMock(return_value={"follower_id": OTHER, "following_id": OWNER}),
        get_followers=AsyncMock(return_value=[]),
        get_following=AsyncMock(return_value=[]),
    )
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[get_optional_current_user_strict] = lambda: (
        AuthenticatedUser(wallet="test-wallet", user_id=viewer, device_id="test-device") if viewer else None
    )
    with TestClient(app) as client:
        response = client.get(f"/{list_name}/{OWNER}")
    allowed = public or viewer == OWNER
    assert response.status_code == (200 if allowed else 404)
    reader = getattr(repo, f"get_{list_name}")
    if allowed:
        reader.assert_awaited_once_with(OWNER, limit=50, offset=0)
    else:
        reader.assert_not_awaited()


@pytest.mark.parametrize("list_name", ["followers", "following"])
def test_expired_private_owner_token_requests_refresh(monkeypatch, list_name):
    # Invalid supplied credentials must not be masked by the visibility lookup.
    from app import dependencies
    monkeypatch.setattr(dependencies, "get_current_user", AsyncMock(side_effect=HTTPException(
        status_code=401, detail="expired", headers={"WWW-Authenticate": "Bearer"})))
    repo = SimpleNamespace(get_user_by_id=AsyncMock(return_value={"id": OWNER, "is_public": False}))
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[dependencies.get_user_repository] = lambda: None
    with TestClient(app) as client:
        response = client.get(f"/{list_name}/{OWNER}", headers={"Authorization": "Bearer expired-token"})
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    repo.get_user_by_id.assert_not_awaited()


@pytest.mark.parametrize("status_code", [401, 503])
@pytest.mark.parametrize("list_name", ["followers", "following"])
def test_social_authentication_preserves_outage_and_credential_errors(monkeypatch, status_code, list_name):
    from app import dependencies
    error = HTTPException(status_code=status_code, detail="upstream auth result",
                          headers={"WWW-Authenticate": "Bearer"} if status_code == 401 else {"Retry-After": "30"})
    monkeypatch.setattr(dependencies, "get_current_user", AsyncMock(side_effect=error))
    repo = SimpleNamespace(get_user_by_id=AsyncMock())
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_repository] = lambda: repo
    app.dependency_overrides[dependencies.get_user_repository] = lambda: None
    with TestClient(app) as client:
        response = client.get(f"/{list_name}/{OWNER}", headers={"Authorization": "Bearer opaque-token"})
    assert response.status_code == status_code
    assert response.json()["detail"] == "upstream auth result"
    if status_code == 503:
        assert response.headers["retry-after"] == "30"
    repo.get_user_by_id.assert_not_awaited()
