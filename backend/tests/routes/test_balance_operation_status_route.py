from __future__ import annotations

import os
from types import SimpleNamespace

from fastapi.testclient import TestClient

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from app.dependencies import AuthenticatedUser, get_current_user, get_repository
from app.main import create_app


RIDER_KEYS = {
    "operation_id",
    "action_type",
    "asset",
    "amount",
    "reference_type",
    "reference_id",
    "rider_state",
    "read_state",
    "pending",
    "delayed",
    "needs_review",
    "recorded",
}
SUPPORT_ONLY_KEYS = {
    "rider_account_id",
    "protocol_wallet",
    "authority_model",
    "source",
    "destination",
    "idempotency_key",
    "prepared_message_hash",
    "fee_payer",
    "policy_or_delegate_id",
    "tx_signature",
    "confirmation_status",
    "projection_status",
    "retry_count",
    "failure_reason",
    "metadata",
}


def test_same_rider_can_read_operation_with_exact_rider_safe_fields() -> None:
    client, _ = _client()

    response = client.get("/balance/operations/op-owned")

    assert response.status_code == 200
    assert set(response.json()) == RIDER_KEYS
    assert not (set(response.json()) & SUPPORT_ONLY_KEYS)
    assert response.json()["operation_id"] == "op-owned"
    assert response.json()["read_state"] == "recorded"


def test_other_rider_operation_is_indistinguishable_from_missing() -> None:
    client, _ = _client()

    response = client.get("/balance/operations/op-other")

    assert response.status_code == 404


def test_same_rider_lookup_uses_client_request_reference_and_action() -> None:
    client, repo = _client()

    response = client.get(
        "/balance/operations/lookup",
        params={
            "client_request_id": "request-owned",
            "reference_type": "vault",
            "reference_id": "42",
            "action_type": "deposit_cal",
        },
    )

    assert response.status_code == 200
    assert set(response.json()) == RIDER_KEYS
    assert response.json()["operation_id"] == "op-owned"
    assert repo.client.queries[-1].filters == [
        ("rider_account_id", "rider-owned"),
        ("reference_type", "vault"),
        ("reference_id", "42"),
        ("action_type", "deposit_cal"),
    ]
    assert repo.client.queries[-1].contained == [
        ("metadata", {"client_request_id": "request-owned"})
    ]


def test_other_rider_client_request_lookup_is_not_found() -> None:
    client, _ = _client()

    response = client.get(
        "/balance/operations/lookup",
        params={
            "client_request_id": "request-other",
            "reference_type": "vault",
            "reference_id": "42",
            "action_type": "deposit_cal",
        },
    )

    assert response.status_code == 404


def _client() -> tuple[TestClient, SimpleNamespace]:
    rows = [
        _row(
            operation_id="op-owned",
            rider_account_id="rider-owned",
            client_request_id="request-owned",
        ),
        _row(
            operation_id="op-other",
            rider_account_id="rider-other",
            client_request_id="request-other",
        ),
    ]
    repo = SimpleNamespace(client=_FakeSupabaseClient(rows))
    app = create_app()

    async def current_user_override() -> AuthenticatedUser:
        return AuthenticatedUser(
            wallet="WalletOwned111111111111111111111111111111",
            user_id="rider-owned",
            device_id="device-test",
        )

    async def repository_override():
        yield repo

    app.dependency_overrides[get_current_user] = current_user_override
    app.dependency_overrides[get_repository] = repository_override
    return TestClient(app), repo


def _row(
    *,
    operation_id: str,
    rider_account_id: str,
    client_request_id: str,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "rider_account_id": rider_account_id,
        "protocol_wallet": "WalletSupport11111111111111111111111111111",
        "action_type": "deposit_cal",
        "authority_model": "app_balance",
        "asset": "CAL",
        "amount": "250000000000",
        "source": "RiderBalance CAL token PDA",
        "destination": "vault:42:cal_escrow",
        "idempotency_key": f"deposit:{client_request_id}",
        "prepared_message_hash": "prepared-hash",
        "fee_payer": "FeePayerSupportOnly",
        "policy_or_delegate_id": "PolicySupportOnly",
        "tx_signature": "SignatureSupportOnly",
        "confirmation_status": "finalized",
        "projection_status": "recorded",
        "retry_count": 0,
        "failure_reason": "SupportOnlyFailure",
        "reference_type": "vault",
        "reference_id": "42",
        "rider_state": "Pending",
        "metadata": {
            "client_request_id": client_request_id,
            "support_note": "SupportOnlyMetadata",
        },
    }


class _FakeSupabaseClient:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.queries: list[_FakeSupabaseQuery] = []

    def table(self, table_name: str) -> "_FakeSupabaseQuery":
        assert table_name == "balance_operations"
        query = _FakeSupabaseQuery(self.rows)
        self.queries.append(query)
        return query


class _FakeSupabaseQuery:
    def __init__(self, rows: list[dict[str, object]]) -> None:
        self.rows = rows
        self.filters: list[tuple[str, object]] = []
        self.contained: list[tuple[str, object]] = []
        self.limit_count: int | None = None

    def select(self, _columns: str) -> "_FakeSupabaseQuery":
        return self

    def eq(self, field: str, value: object) -> "_FakeSupabaseQuery":
        self.filters.append((field, value))
        return self

    def contains(self, field: str, value: object) -> "_FakeSupabaseQuery":
        self.contained.append((field, value))
        return self

    def order(self, _field: str, *, desc: bool = False) -> "_FakeSupabaseQuery":
        if desc:
            self.rows = list(reversed(self.rows))
        return self

    def limit(self, count: int) -> "_FakeSupabaseQuery":
        self.limit_count = count
        return self

    def execute(self) -> SimpleNamespace:
        rows = [
            row
            for row in self.rows
            if all(row.get(field) == value for field, value in self.filters)
            and all(
                isinstance(row.get(field), dict)
                and all(row[field].get(key) == nested for key, nested in value.items())
                for field, value in self.contained
            )
        ]
        if self.limit_count is not None:
            rows = rows[: self.limit_count]
        return SimpleNamespace(data=rows)
