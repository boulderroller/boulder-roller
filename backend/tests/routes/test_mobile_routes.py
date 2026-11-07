"""Mobile operability endpoints (boulderroller-v2-k7387): crash-diagnostic
ingest is authenticated, size-capped, and type-allowlisted; push device
registration is authenticated, validated, replaceable, and wallet-guarded."""
from __future__ import annotations

import os
from typing import Any

os.environ.setdefault("ACCESS_TOKEN_SECRET", "test-access-secret")
os.environ.setdefault("REFRESH_TOKEN_SECRET", "test-refresh-secret")
os.environ.setdefault("AUTH_AUDIENCE", "test-audience")

from fastapi import FastAPI, HTTPException, status
from fastapi.testclient import TestClient

from app.dependencies import AuthenticatedUser, get_current_user
from app.routes.mobile import (
    MAX_DIAGNOSTIC_BYTES,
    MAX_DIAGNOSTICS_PER_REQUEST,
    get_mobile_ops_repository,
    router,
)


class FakeMobileOpsRepository:
    def __init__(self) -> None:
        self.inserted_diagnostics: list[dict[str, Any]] = []
        self.upserts: list[dict[str, Any]] = []
        self.deletes: list[dict[str, Any]] = []

    async def insert_diagnostics(self, rows: list[dict[str, Any]]) -> int:
        self.inserted_diagnostics.extend(rows)
        return len(rows)

    async def upsert_push_device(self, **kwargs: Any) -> None:
        self.upserts.append(kwargs)

    async def delete_push_device(self, *, device_id: str, wallet: str) -> bool:
        self.deletes.append({"device_id": device_id, "wallet": wallet})
        return device_id == "known-device-00000000"


def _user() -> AuthenticatedUser:
    return AuthenticatedUser(
        wallet="RiderWallet1111111111111111111111111111111",
        user_id="rider-user",
        device_id="device-abc",
    )


def _app(repo: FakeMobileOpsRepository, *, authenticated: bool = True) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_mobile_ops_repository] = lambda: repo
    if authenticated:
        app.dependency_overrides[get_current_user] = _user
    else:
        async def reject_user() -> None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication token",
            )

        app.dependency_overrides[get_current_user] = reject_user
    return app


def _envelope(**overrides: Any) -> dict[str, Any]:
    envelope: dict[str, Any] = {
        "schema": 1,
        "diagnostic_type": "crash",
        "captured_at": "2026-08-12T01:00:00Z",
        "app_version": "0.1.0",
        "build_number": "2126",
        "os_version": "iOS 26.3",
        "device_model": "iPhone17,3",
        "payload": {"callStackTree": {"callStacks": []}},
    }
    envelope.update(overrides)
    return envelope


# ---------------------------------------------------------------------------
# Diagnostics ingest
# ---------------------------------------------------------------------------

def test_diagnostics_ingest_requires_authentication() -> None:
    client = TestClient(_app(FakeMobileOpsRepository(), authenticated=False))
    response = client.post("/mobile/diagnostics", json={"diagnostics": [_envelope()]})
    assert response.status_code == 401


def test_diagnostics_ingest_stores_wallet_bound_rows() -> None:
    repo = FakeMobileOpsRepository()
    client = TestClient(_app(repo))
    response = client.post(
        "/mobile/diagnostics",
        json={"diagnostics": [_envelope(), _envelope(diagnostic_type="hang")]},
    )
    assert response.status_code == 200
    assert response.json() == {"accepted": 2}
    assert len(repo.inserted_diagnostics) == 2
    row = repo.inserted_diagnostics[0]
    assert row["wallet"] == _user().wallet
    assert row["device_id"] == "device-abc"
    assert row["diagnostic_type"] == "crash"
    assert row["build_number"] == "2126"
    assert row["payload"] == {"callStackTree": {"callStacks": []}}
    assert row["payload_bytes"] > 0


def test_diagnostics_ingest_accepts_debug_forced_test_type() -> None:
    repo = FakeMobileOpsRepository()
    client = TestClient(_app(repo))
    response = client.post(
        "/mobile/diagnostics",
        json={
            "diagnostics": [
                _envelope(diagnostic_type="debug_forced_test", payload={"simulated": True})
            ]
        },
    )
    assert response.status_code == 200
    assert repo.inserted_diagnostics[0]["diagnostic_type"] == "debug_forced_test"


def test_diagnostics_ingest_rejects_unknown_type_fail_closed() -> None:
    repo = FakeMobileOpsRepository()
    client = TestClient(_app(repo))
    response = client.post(
        "/mobile/diagnostics",
        json={"diagnostics": [_envelope(diagnostic_type="location_trace")]},
    )
    assert response.status_code == 422
    assert repo.inserted_diagnostics == []


def test_diagnostics_ingest_rejects_missing_payload() -> None:
    client = TestClient(_app(FakeMobileOpsRepository()))
    response = client.post(
        "/mobile/diagnostics", json={"diagnostics": [_envelope(payload={})]}
    )
    assert response.status_code == 422


def test_diagnostics_ingest_caps_batch_size() -> None:
    client = TestClient(_app(FakeMobileOpsRepository()))
    batch = [_envelope() for _ in range(MAX_DIAGNOSTICS_PER_REQUEST + 1)]
    response = client.post("/mobile/diagnostics", json={"diagnostics": batch})
    assert response.status_code == 413


def test_diagnostics_ingest_caps_envelope_bytes() -> None:
    client = TestClient(_app(FakeMobileOpsRepository()))
    oversize = _envelope(payload={"blob": "x" * MAX_DIAGNOSTIC_BYTES})
    response = client.post("/mobile/diagnostics", json={"diagnostics": [oversize]})
    assert response.status_code == 413


# ---------------------------------------------------------------------------
# Push device registration
# ---------------------------------------------------------------------------

def test_push_device_registration_upserts_for_the_authenticated_wallet() -> None:
    repo = FakeMobileOpsRepository()
    client = TestClient(_app(repo))
    response = client.post(
        "/mobile/push/devices",
        json={
            "device_id": "device-abc-12345678",
            "apns_token": "AB" * 32,
            "environment": "sandbox",
            "app_version": "0.1.0",
        },
    )
    assert response.status_code == 200
    assert response.json() == {"device_id": "device-abc-12345678"}
    assert repo.upserts == [
        {
            "device_id": "device-abc-12345678",
            "wallet": _user().wallet,
            "apns_token": "ab" * 32,
            "environment": "sandbox",
            "app_version": "0.1.0",
        }
    ]


def test_push_device_registration_requires_authentication() -> None:
    client = TestClient(_app(FakeMobileOpsRepository(), authenticated=False))
    response = client.post(
        "/mobile/push/devices",
        json={
            "device_id": "device-abc-12345678",
            "apns_token": "ab" * 32,
            "environment": "sandbox",
        },
    )
    assert response.status_code == 401


def test_push_device_registration_validates_token_and_environment() -> None:
    client = TestClient(_app(FakeMobileOpsRepository()))
    not_hex = client.post(
        "/mobile/push/devices",
        json={
            "device_id": "device-abc-12345678",
            "apns_token": "zz-not-hex-token-zz",
            "environment": "sandbox",
        },
    )
    assert not_hex.status_code == 422
    bad_env = client.post(
        "/mobile/push/devices",
        json={
            "device_id": "device-abc-12345678",
            "apns_token": "ab" * 32,
            "environment": "staging",
        },
    )
    assert bad_env.status_code == 422


def test_push_device_unregistration_is_wallet_guarded() -> None:
    repo = FakeMobileOpsRepository()
    client = TestClient(_app(repo))
    known = client.delete("/mobile/push/devices/known-device-00000000")
    assert known.status_code == 200
    assert known.json() == {"removed": True}
    unknown = client.delete("/mobile/push/devices/someone-elses-device")
    assert unknown.status_code == 200
    assert unknown.json() == {"removed": False}
    assert all(item["wallet"] == _user().wallet for item in repo.deletes)
