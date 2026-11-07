import os
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import pytest

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_SIGNATURE_BYPASS", "true")

from app.routes.admin import (
    get_ride_economic_review_repository,
    get_ride_economic_review_service,
    require_admin,
    router,
)


RIDE_ID = UUID("10000000-0000-0000-0000-000000000001")
ADMIN_ID = UUID("20000000-0000-0000-0000-000000000001")
REQUEST_ID = UUID("30000000-0000-0000-0000-000000000001")


def _client(*, admin_dependency, repository=None, service=None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[require_admin] = admin_dependency
    if repository is not None:
        app.dependency_overrides[get_ride_economic_review_repository] = (
            lambda: repository
        )
    if service is not None:
        app.dependency_overrides[get_ride_economic_review_service] = lambda: service
    return TestClient(app)


async def _admin():
    return ADMIN_ID, "admin"


async def _denied():
    raise HTTPException(status_code=403, detail="Admin access required")


def _resolution_payload() -> dict:
    return {
        "request_id": str(REQUEST_ID),
        "review_version": 2,
        "outcome": "resume",
        "selected_checkpoint": "planned",
        "reason": "finalized account snapshot proves a clean restart",
        "liability_disposition": None,
        "effects_disposition": None,
    }


def test_review_inspection_and_resolution_require_admin() -> None:
    repository = SimpleNamespace(get_review=AsyncMock())
    service = SimpleNamespace(resolve=AsyncMock())
    client = _client(
        admin_dependency=_denied,
        repository=repository,
        service=service,
    )

    assert client.get(f"/admin/ride-economics/{RIDE_ID}/review").status_code == 403
    assert (
        client.post(
            f"/admin/ride-economics/{RIDE_ID}/review/resolve",
            json=_resolution_payload(),
        ).status_code
        == 403
    )
    repository.get_review.assert_not_awaited()
    service.resolve.assert_not_awaited()


def test_resolution_payload_rejects_forged_chain_evidence() -> None:
    service = SimpleNamespace(resolve=AsyncMock())
    client = _client(admin_dependency=_admin, service=service)
    payload = _resolution_payload()
    payload["chain_evidence"] = {
        "commitment": "finalized",
        "forged": True,
    }

    response = client.post(
        f"/admin/ride-economics/{RIDE_ID}/review/resolve",
        json=payload,
    )

    assert response.status_code == 422
    service.resolve.assert_not_awaited()


@pytest.mark.parametrize(
    "field",
    ("liability_disposition", "effects_disposition"),
)
def test_resolution_payload_rejects_unbounded_dispositions(field: str) -> None:
    service = SimpleNamespace(resolve=AsyncMock())
    client = _client(admin_dependency=_admin, service=service)
    payload = _resolution_payload()
    payload.update(
        {
            "outcome": "reject",
            "selected_checkpoint": None,
            "liability_disposition": "liability accepted",
            "effects_disposition": "effects retained",
            field: "x" * 2001,
        }
    )

    response = client.post(
        f"/admin/ride-economics/{RIDE_ID}/review/resolve",
        json=payload,
    )

    assert response.status_code == 422
    service.resolve.assert_not_awaited()


def test_resolution_payload_accepts_2000_character_dispositions() -> None:
    service = SimpleNamespace(
        resolve=AsyncMock(
            return_value={
                "request_id": str(REQUEST_ID),
                "outcome": "reject",
                "result_state": "rejected",
                "replayed": False,
            }
        )
    )
    client = _client(admin_dependency=_admin, service=service)
    payload = _resolution_payload()
    payload.update(
        {
            "outcome": "reject",
            "selected_checkpoint": None,
            "liability_disposition": "l" * 2000,
            "effects_disposition": "e" * 2000,
        }
    )

    response = client.post(
        f"/admin/ride-economics/{RIDE_ID}/review/resolve",
        json=payload,
    )

    assert response.status_code == 200
    service.resolve.assert_awaited_once()


def test_admin_actor_is_derived_and_verified_service_handles_resolution() -> None:
    service = SimpleNamespace(
        resolve=AsyncMock(
            return_value={
                "request_id": str(REQUEST_ID),
                "outcome": "resume",
                "result_state": "planned",
                "replayed": False,
            }
        )
    )
    client = _client(admin_dependency=_admin, service=service)

    response = client.post(
        f"/admin/ride-economics/{RIDE_ID}/review/resolve",
        json=_resolution_payload(),
    )

    assert response.status_code == 200
    assert response.json()["result_state"] == "planned"
    service.resolve.assert_awaited_once_with(
        ride_id=RIDE_ID,
        expected_review_version=2,
        request_id=REQUEST_ID,
        actor_id=ADMIN_ID,
        outcome="resume",
        selected_checkpoint="planned",
        reason="finalized account snapshot proves a clean restart",
        liability_disposition=None,
        effects_disposition=None,
    )


def test_same_admin_request_can_replay_after_a_lost_response() -> None:
    stored = {
        "request_id": str(REQUEST_ID),
        "outcome": "resume",
        "result_state": "planned",
        "chain_evidence": {"finalized_slot": "100"},
    }
    service = SimpleNamespace(
        resolve=AsyncMock(
            side_effect=[
                {**stored, "replayed": False},
                {**stored, "replayed": True},
            ]
        )
    )
    client = _client(admin_dependency=_admin, service=service)
    path = f"/admin/ride-economics/{RIDE_ID}/review/resolve"

    first = client.post(path, json=_resolution_payload())
    replay = client.post(path, json=_resolution_payload())

    assert first.status_code == 200
    assert replay.status_code == 200
    assert first.json()["replayed"] is False
    assert replay.json()["replayed"] is True
    assert replay.json()["chain_evidence"] == first.json()["chain_evidence"]
    assert service.resolve.await_count == 2


def test_admin_can_inspect_versioned_review() -> None:
    repository = SimpleNamespace(
        get_review=AsyncMock(
            return_value={
                "plan": {"ride_id": str(RIDE_ID), "state": "review"},
                "review": {"review_version": 2, "prior_state": "planned"},
                "resolution": None,
            }
        )
    )
    client = _client(admin_dependency=_admin, repository=repository)

    response = client.get(f"/admin/ride-economics/{RIDE_ID}/review")

    assert response.status_code == 200
    assert response.json()["review"]["review_version"] == 2
    repository.get_review.assert_awaited_once_with(RIDE_ID)
