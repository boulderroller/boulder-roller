"""L3.08 app→API version contract (bead boulderroller-v2-f4acp.2.8).

The contract is additive: requests without the headers pass untouched.
A declared-but-unsupported contract, or a build under the operator floor,
receives the typed 426 upgrade refusal and nothing else changes.
"""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.middleware.client_contract import (
    CLIENT_HEADER,
    CONTRACT_HEADER,
    ClientContractMiddleware,
    minimum_supported_build,
    parse_client,
)


def make_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(ClientContractMiddleware)

    @app.get("/rides/list")
    def rides() -> dict[str, bool]:
        return {"ok": True}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


def test_requests_without_headers_pass_untouched() -> None:
    client = TestClient(make_app())
    response = client.get("/rides/list")
    assert response.status_code == 200
    assert response.json() == {"ok": True}


def test_supported_contract_passes() -> None:
    client = TestClient(make_app())
    response = client.get(
        "/rides/list",
        headers={CONTRACT_HEADER: "client.v1", CLIENT_HEADER: "ios/214"},
    )
    assert response.status_code == 200


def test_unsupported_contract_gets_typed_upgrade_refusal() -> None:
    client = TestClient(make_app())
    response = client.get(
        "/rides/list", headers={CONTRACT_HEADER: "client.v9"}
    )
    assert response.status_code == 426
    assert response.json() == {"detail": {"code": "upgrade_required"}}


def test_build_floor_refuses_only_older_builds(monkeypatch) -> None:
    monkeypatch.setenv("BR_MIN_SUPPORTED_IOS_BUILD", "100")
    client = TestClient(make_app())

    old = client.get(
        "/rides/list",
        headers={CONTRACT_HEADER: "client.v1", CLIENT_HEADER: "ios/99"},
    )
    assert old.status_code == 426
    assert old.json() == {"detail": {"code": "upgrade_required"}}

    current = client.get(
        "/rides/list",
        headers={CONTRACT_HEADER: "client.v1", CLIENT_HEADER: "ios/100"},
    )
    assert current.status_code == 200


def test_health_and_status_stay_reachable_for_any_build(monkeypatch) -> None:
    monkeypatch.setenv("BR_MIN_SUPPORTED_IOS_BUILD", "10000")
    client = TestClient(make_app())
    response = client.get(
        "/health", headers={CONTRACT_HEADER: "client.v9", CLIENT_HEADER: "ios/1"}
    )
    assert response.status_code == 200


def test_malformed_client_values_never_refuse(monkeypatch) -> None:
    monkeypatch.setenv("BR_MIN_SUPPORTED_IOS_BUILD", "100")
    client = TestClient(make_app())
    for value in ("ios", "ios/", "ios/banana", "/12", ""):
        response = client.get(
            "/rides/list",
            headers={CONTRACT_HEADER: "client.v1", CLIENT_HEADER: value},
        )
        assert response.status_code == 200, value


def test_parse_and_floor_helpers() -> None:
    assert parse_client("ios/214") == ("ios", 214)
    assert parse_client("IOS/7") == ("ios", 7)
    assert parse_client("garbage") is None
    assert minimum_supported_build("android") == 0
