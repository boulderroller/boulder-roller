from __future__ import annotations

import base64
import math
import os
import re
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch
from uuid import UUID, uuid4

os.environ.setdefault("ACCESS_TOKEN_SECRET", "account-deletion-test-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "account-deletion-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "account-deletion-test-audience")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.dependencies import AuthenticatedUser, get_current_user
from app.rate_limits_config import RATE_LIMITS
from app.routes.compliance import (
    get_account_deletion_dispatcher,
    get_account_deletion_preflight_reader,
    get_account_deletion_repository,
    router,
)
from app.services.account_deletion import (
    AccountDeletionValueSnapshot,
    DeletionAssetBalance,
    hash_account_deletion_status_token,
)


USER_ID = str(uuid4())
WALLET = "RiderWallet1111111111111111111111111111111"


def test_portal_status_polling_keeps_headroom_under_the_general_rate_limit() -> None:
    status_screen = (
        Path(__file__).resolve().parents[3]
        / "web/portal/src/components/account/AccountDeletionStatusScreen.tsx"
    ).read_text(encoding="utf-8")
    match = re.search(r"POLL_BASE_DELAY_MS\s*=\s*(\d+)", status_screen)
    assert match, "Account deletion status polling cadence must remain explicit"
    base_delay_ms = int(match.group(1))
    general_limit = RATE_LIMITS["general"]
    assert math.ceil(60_000 / base_delay_ms) <= math.floor(
        general_limit.requests_per_minute * 0.8
    )
    assert math.ceil(3_600_000 / base_delay_ms) <= math.floor(
        general_limit.requests_per_hour * 0.8
    )


class FakeDeletionRepository:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.rows: dict[str, dict] = {}
        self.dispatch_failures: list[str] = []
        self.retry_prepares: list[tuple[str, dict]] = []
        self.create_error: Exception | None = None
        self.retry_error: Exception | None = None

    async def log_audit_event(self, **_kwargs) -> str:
        return "audit-1"

    async def create_deletion_request(self, **kwargs) -> dict:
        if self.create_error:
            raise self.create_error
        self.created.append(kwargs)
        request_id = str(kwargs["request_id"])
        preflight = kwargs["preflight_snapshot"]
        blockers = list(preflight.get("blockers") or [])
        if not preflight.get("available"):
            request_status = "failed_retryable"
        elif any(blocker.get("code") == "policy_review_required" for blocker in blockers):
            request_status = "needs_support"
        elif blockers:
            request_status = "blocked"
        else:
            request_status = "queued"
        row = {
            "id": request_id,
            "user_id": USER_ID,
            "wallet": WALLET,
            "status_token_hash": kwargs["status_token_hash"],
            "status": request_status,
            "requested_at": "2026-08-24T17:00:00Z",
            "updated_at": "2026-08-24T17:00:00Z",
            "completed_at": None,
            "blockers": blockers,
            "failure_code": "preflight_unavailable" if request_status == "failed_retryable" else None,
            "retryable": request_status != "needs_support",
            "attempt_count": 0,
        }
        self.rows[request_id] = row
        return row

    async def get_deletion_request(self, request_id: UUID | str) -> dict | None:
        return self.rows.get(str(request_id))

    async def mark_dispatch_failed(self, request_id: str) -> dict:
        self.dispatch_failures.append(request_id)
        self.rows[request_id].update(
            status="failed_retryable",
            failure_code="queue_unavailable",
            retryable=True,
        )
        return self.rows[request_id]

    async def mark_blocked(self, request_id: str, blockers) -> None:
        self.rows[request_id].update(
            status="blocked",
            blockers=[blocker.as_dict() for blocker in blockers],
            retryable=True,
        )

    async def prepare_deletion_retry(
        self,
        request_id: str,
        *,
        preflight_snapshot: dict,
    ) -> dict:
        if self.retry_error:
            raise self.retry_error
        self.retry_prepares.append((request_id, preflight_snapshot))
        blockers = list(preflight_snapshot.get("blockers") or [])
        if not preflight_snapshot.get("available"):
            status = "failed_retryable"
        elif any(blocker.get("code") == "policy_review_required" for blocker in blockers):
            status = "needs_support"
        elif blockers:
            status = "blocked"
        else:
            status = "queued"
        self.rows[request_id].update(
            status=status,
            blockers=blockers,
            failure_code=None,
            retryable=status != "needs_support",
        )
        return self.rows[request_id]


def _snapshot(**overrides) -> AccountDeletionValueSnapshot:
    values = {
        "balances": (),
        "active_stakes": 0,
        "pending_claims": 0,
        "unresolved_provenance": 0,
        "unavailable_sources": (),
        "destructive_boundary_available": True,
    }
    values.update(overrides)
    return AccountDeletionValueSnapshot(**values)


def _client(
    repository: FakeDeletionRepository,
    *,
    snapshot: AccountDeletionValueSnapshot | None = None,
    dispatcher: Mock | None = None,
    raise_server_exceptions: bool = True,
) -> tuple[TestClient, AsyncMock, Mock]:
    app = FastAPI()
    app.include_router(router)
    reader = AsyncMock()
    reader.read.return_value = snapshot or _snapshot()
    dispatcher = dispatcher or Mock()
    app.dependency_overrides[get_current_user] = lambda: AuthenticatedUser(
        wallet=WALLET,
        user_id=USER_ID,
        device_id="device-1",
    )
    app.dependency_overrides[get_account_deletion_repository] = lambda: repository
    app.dependency_overrides[get_account_deletion_preflight_reader] = lambda: reader
    app.dependency_overrides[get_account_deletion_dispatcher] = lambda: dispatcher
    return (
        TestClient(app, raise_server_exceptions=raise_server_exceptions),
        reader,
        dispatcher,
    )


def _request_body(**overrides) -> dict:
    body = {
        "request_id": str(uuid4()),
        "status_token": "A" * 43,
        "unuploaded_rides_acknowledged": True,
    }
    body.update(overrides)
    return body


def test_route_uses_the_shared_account_deletion_authority_builder() -> None:
    repository = FakeDeletionRepository()
    reader = object()
    with patch(
        "app.routes.compliance.build_account_deletion_authority_reader",
        return_value=reader,
    ) as build_reader:
        result = get_account_deletion_preflight_reader(repository)

    assert result is reader
    build_reader.assert_called_once_with(repository)


def test_preflight_block_is_durable_and_never_dispatched() -> None:
    repository = FakeDeletionRepository()
    client, _, dispatcher = _client(
        repository,
        snapshot=_snapshot(
            balances=(
                DeletionAssetBalance(
                    asset="CAL",
                    amount_base_units=1,
                    source="boulder_roller_balance",
                ),
            )
        ),
    )

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 202
    assert response.json()["status"] == "blocked"
    assert response.json()["blockers"][0]["code"] == "balance_remains"
    assert len(repository.created) == 1
    dispatcher.enqueue.assert_not_called()


def test_human_gate_request_is_filed_and_routed_to_needs_support() -> None:
    repository = FakeDeletionRepository()
    client, _, dispatcher = _client(
        repository,
        snapshot=_snapshot(destructive_boundary_available=False),
    )

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 202
    assert response.json()["status"] == "needs_support"
    blocker = response.json()["blockers"][0]
    assert blocker["code"] == "policy_review_required"
    assert blocker["category"] == "policy"
    assert blocker["count"] == 1
    assert blocker["source"] == "on_chain_deletion_boundary"
    assert blocker["action"] == "contact_support"
    assert len(repository.created) == 1
    dispatcher.enqueue.assert_not_called()


def test_unuploaded_rides_must_be_acknowledged_before_request_creation() -> None:
    repository = FakeDeletionRepository()
    client, _, dispatcher = _client(repository)

    response = client.request(
        "DELETE",
        "/compliance/account",
        json=_request_body(unuploaded_rides_acknowledged=False),
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "unuploaded_rides_unacknowledged"
    assert repository.created == []
    dispatcher.enqueue.assert_not_called()


def test_accepted_request_is_queued_and_never_reported_completed() -> None:
    repository = FakeDeletionRepository()
    client, _, dispatcher = _client(repository)

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert payload["completed_at"] is None
    assert payload["request_id"]
    assert "status_token" not in payload
    dispatcher.enqueue.assert_called_once_with(payload["request_id"])


def test_queue_failure_is_a_readable_retryable_state_not_false_completion() -> None:
    repository = FakeDeletionRepository()
    dispatcher = Mock()
    dispatcher.enqueue.side_effect = RuntimeError("queue unavailable")
    client, _, _ = _client(repository, dispatcher=dispatcher)

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 202
    assert response.json()["status"] == "failed_retryable"
    assert response.json()["failure_code"] == "queue_unavailable"
    assert len(repository.dispatch_failures) == 1


def test_status_capability_remains_readable_without_authenticated_dependency() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    request_body = _request_body()
    create = client.request("DELETE", "/compliance/account", json=request_body).json()
    request_id = create["request_id"]
    repository.rows[request_id].update(
        status="completed",
        completed_at="2026-08-24T17:01:00Z",
        retryable=False,
        wallet=None,
        completion_verified_at="2026-08-24T17:01:00Z",
    )

    response = client.get(
        f"/compliance/deletion-status/{request_id}",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["completed_at"] == "2026-08-24T17:01:00Z"


def test_status_capability_rejects_an_invalid_token_without_leaking_request() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    create = client.request("DELETE", "/compliance/account", json=_request_body()).json()

    response = client.get(
        f"/compliance/deletion-status/{create['request_id']}",
        headers={"X-Account-Deletion-Token": "wrong-token"},
    )

    assert response.status_code == 404


def test_legacy_unverified_status_never_exposes_a_completion_timestamp() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    request_body = _request_body()
    request_id = client.request(
        "DELETE", "/compliance/account", json=request_body
    ).json()["request_id"]
    repository.rows[request_id].update(
        status="legacy_unverified",
        completed_at="2026-08-24T17:01:00Z",
        completion_verified_at=None,
        retryable=False,
    )

    response = client.get(
        f"/compliance/deletion-status/{request_id}",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "legacy_unverified"
    assert response.json()["completed_at"] is None


def test_retry_rechecks_server_preflight_before_dispatch() -> None:
    repository = FakeDeletionRepository()
    ready_client, _, _ = _client(repository)
    request_body = _request_body()
    create = ready_client.request("DELETE", "/compliance/account", json=request_body).json()
    request_id = create["request_id"]
    repository.rows[request_id]["status"] = "failed_retryable"
    blocked_client, _, dispatcher = _client(
        repository,
        snapshot=_snapshot(active_stakes=1),
    )

    response = blocked_client.post(
        f"/compliance/deletion-status/{request_id}/retry",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
        json={},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "blocked"
    dispatcher.enqueue.assert_not_called()


def test_retry_does_not_convert_a_recoverable_request_to_terminal_support() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    request_body = _request_body()
    request_id = client.request(
        "DELETE", "/compliance/account", json=request_body
    ).json()["request_id"]
    repository.rows[request_id]["status"] = "failed_retryable"
    retry_client, _, dispatcher = _client(
        repository,
        snapshot=_snapshot(destructive_boundary_available=False),
    )

    response = retry_client.post(
        f"/compliance/deletion-status/{request_id}/retry",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
        json={},
    )

    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "retry_requires_support"
    assert repository.rows[request_id]["status"] == "failed_retryable"
    assert repository.retry_prepares == []
    dispatcher.enqueue.assert_not_called()


def test_retry_cannot_reassert_the_durable_unuploaded_rides_acknowledgement() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    request_body = _request_body()
    request_id = client.request(
        "DELETE", "/compliance/account", json=request_body
    ).json()["request_id"]
    repository.rows[request_id]["status"] = "failed_retryable"

    response = client.post(
        f"/compliance/deletion-status/{request_id}/retry",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
        json={"unuploaded_rides_acknowledged": True},
    )

    assert response.status_code == 422
    assert repository.retry_prepares == []


def test_create_translates_lifecycle_conflicts_to_a_readable_409() -> None:
    expected = {
        "account_deletion_request_already_active": "request_already_active",
        "account_deletion_user_unavailable": "account_unavailable",
        "account_deletion_request_id_conflict": "request_id_conflict",
    }
    for database_error, response_code in expected.items():
        repository = FakeDeletionRepository()
        repository.create_error = RuntimeError(database_error)
        client, _, dispatcher = _client(repository)

        response = client.request("DELETE", "/compliance/account", json=_request_body())

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == response_code
        dispatcher.enqueue.assert_not_called()


def test_retry_translates_lifecycle_conflicts_to_a_readable_409() -> None:
    expected = {
        "account_deletion_user_unavailable": "account_unavailable",
        "account_deletion_retry_unavailable": "retry_unavailable",
        "account_deletion_retry_requires_support": "retry_requires_support",
    }
    for database_error, response_code in expected.items():
        repository = FakeDeletionRepository()
        client, _, _ = _client(repository)
        request_body = _request_body()
        request_id = client.request(
            "DELETE", "/compliance/account", json=request_body
        ).json()["request_id"]
        repository.rows[request_id]["status"] = "failed_retryable"
        repository.retry_error = RuntimeError(database_error)

        response = client.post(
            f"/compliance/deletion-status/{request_id}/retry",
            headers={"X-Account-Deletion-Token": request_body["status_token"]},
            json={},
        )

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == response_code


def test_unrelated_database_errors_remain_visible_server_failures() -> None:
    repository = FakeDeletionRepository()
    repository.create_error = RuntimeError("database unavailable")
    client, _, dispatcher = _client(
        repository,
        raise_server_exceptions=False,
    )

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 500
    dispatcher.enqueue.assert_not_called()


def test_client_request_identity_is_idempotent_without_echoing_the_capability() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    request_body = _request_body()

    first = client.request("DELETE", "/compliance/account", json=request_body)
    second = client.request("DELETE", "/compliance/account", json=request_body)

    assert first.status_code == 202
    assert second.status_code == 202
    assert first.json()["request_id"] == request_body["request_id"]
    assert second.json()["request_id"] == request_body["request_id"]
    assert "status_token" not in first.json()


def test_blocker_amount_is_an_exact_decimal_string_on_the_wire() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(
        repository,
        snapshot=_snapshot(
            balances=(
                DeletionAssetBalance(
                    asset="CAL",
                    amount_base_units=9_007_199_254_740_993,
                    source="boulder_roller_balance",
                ),
            )
        ),
    )

    response = client.request("DELETE", "/compliance/account", json=_request_body())

    assert response.status_code == 202
    assert response.json()["blockers"][0][
        "amount_base_units"
    ] == "9007199254740993"


def test_client_can_recover_status_after_the_create_response_is_lost() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)
    status_token = base64.urlsafe_b64encode(b"B" * 32).decode().rstrip("=")
    request_body = _request_body(status_token=status_token)

    client.request("DELETE", "/compliance/account", json=request_body)
    response = client.get(
        f"/compliance/deletion-status/{request_body['request_id']}",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
    )

    assert response.status_code == 200
    assert response.json()["request_id"] == request_body["request_id"]
    assert response.json()["status"] == "queued"


def test_deletion_lifecycle_responses_are_private_and_not_cacheable() -> None:
    repository = FakeDeletionRepository()
    client, _, _ = _client(repository)

    preflight = client.get("/compliance/account/preflight")
    request_body = _request_body()
    created = client.request("DELETE", "/compliance/account", json=request_body)
    request_id = created.json()["request_id"]
    status_response = client.get(
        f"/compliance/deletion-status/{request_id}",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
    )
    repository.rows[request_id]["status"] = "failed_retryable"
    retry_response = client.post(
        f"/compliance/deletion-status/{request_id}/retry",
        headers={"X-Account-Deletion-Token": request_body["status_token"]},
        json={},
    )
    not_found = client.get(
        f"/compliance/deletion-status/{request_id}",
        headers={"X-Account-Deletion-Token": "wrong-token"},
    )

    for response in (preflight, created, status_response, retry_response, not_found):
        assert response.headers["cache-control"] == "private, no-store"
