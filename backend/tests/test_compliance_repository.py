from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.compliance_repository import ComplianceRepository
from app.services.account_deletion import AccountDeletionRequest


class _QueryClient:
    def __init__(self, *responses: object) -> None:
        self.responses = list(responses)
        self.rpc_calls: list[tuple[str, dict]] = []
        self.table_calls: list[tuple[str, str]] = []
        self._table = ""

    def rpc(self, operation: str, args: dict) -> "_QueryClient":
        self.rpc_calls.append((operation, args))
        return self

    def table(self, table: str) -> "_QueryClient":
        self._table = table
        return self

    def select(self, columns: str) -> "_QueryClient":
        self.table_calls.append((self._table, columns))
        return self

    def eq(self, _key: str, _value: object) -> "_QueryClient":
        return self

    def limit(self, _limit: int) -> "_QueryClient":
        return self

    def execute(self) -> object:
        response = self.responses.pop(0)
        if isinstance(response, BaseException):
            raise response
        return response


def _repository(*responses: object) -> tuple[ComplianceRepository, _QueryClient]:
    client = _QueryClient(*responses)
    repository = ComplianceRepository.__new__(ComplianceRepository)
    repository._client = client

    async def _run(func):
        return func()

    repository._run = _run
    return repository, client


def _request() -> AccountDeletionRequest:
    return AccountDeletionRequest(
        request_id="request-1",
        user_id="user-1",
        wallet="wallet-1",
        status="processing",
        unuploaded_rides_acknowledged=True,
        storage_paths=("rides/user-1/ride.fit",),
        lease_token="lease-1",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize('current_lease',[False,True])
async def test_keeper_exports_require_current_lease_before_write_and_finalization(tmp_path,monkeypatch,current_lease):
    from app.services.stage1_keeper_worker import export_claims
    job='c'*64
    path,sha=export_claims(tmp_path,job,{'person':'private'})
    manifest={'path':path,'digest':sha,'job_id':job,'payload':{'identity_erased':True}}
    done={'id':'request-1','status':'completed'}
    repository,client=_repository(SimpleNamespace(data={'exports':[manifest],'request':None}),
        SimpleNamespace(data=True) if current_lease else RuntimeError('stale erasure lease'),
        SimpleNamespace(data=True),SimpleNamespace(data=[done]))
    monkeypatch.setenv('STAGE1_KEEPER_EXPORT_DIR',str(tmp_path))
    from pathlib import Path
    before=Path(path).read_bytes()
    if current_lease:
        assert await repository.finalize_anonymization(_request())==done
        assert b'private' not in Path(path).read_bytes()
        assert [name for name,_ in client.rpc_calls]==['stage1_keeper_prepare_erasure',
            'stage1_keeper_validate_erasure','stage1_keeper_record_erasure','finalize_account_anonymization']
    else:
        with pytest.raises(RuntimeError,match='stale erasure lease'):
            await repository.finalize_anonymization(_request())
        assert Path(path).read_bytes()==before
        assert [name for name,_ in client.rpc_calls]==['stage1_keeper_prepare_erasure','stage1_keeper_validate_erasure']


@pytest.mark.asyncio
async def test_dispatch_failure_race_returns_the_concurrently_claimed_row() -> None:
    claimed = {
        "id": "request-1",
        "status": "processing",
        "worker_lease_token": "lease-1",
    }
    repository, client = _repository(
        SimpleNamespace(data=[]),
        SimpleNamespace(data=[claimed]),
    )

    row = await repository.mark_dispatch_failed("request-1")

    assert row == claimed
    assert client.rpc_calls == [
        ("fail_account_deletion_dispatch", {"p_request_id": "request-1"})
    ]
    assert client.table_calls == [("deletion_requests", "*")]


@pytest.mark.asyncio
async def test_claim_maps_the_durable_row_and_lease_token() -> None:
    claimed = {
        "id": "request-1",
        "user_id": "user-1",
        "wallet": "wallet-1",
        "status": "processing",
        "unuploaded_rides_acknowledged": True,
        "storage_paths": ["rides/user-1/ride.fit"],
        "worker_lease_token": "lease-1",
    }
    repository, client = _repository(SimpleNamespace(data=[claimed]))

    request = await repository.claim_for_processing("request-1")

    assert request == _request()
    operation, args = client.rpc_calls[0]
    assert operation == "claim_account_deletion_request"
    assert args["p_request_id"] == "request-1"
    assert args["p_lease_seconds"] == 300
    assert args["p_worker_id"]


@pytest.mark.asyncio
async def test_database_blocker_authority_rejects_a_malformed_payload() -> None:
    repository, _ = _repository(SimpleNamespace(data={"code": "claim_remains"}))

    with pytest.raises(RuntimeError, match="malformed payload"):
        await repository.get_deletion_database_blockers("user-1", "wallet-1")


@pytest.mark.asyncio
async def test_storage_authorization_calls_the_atomic_database_gate() -> None:
    authorized = {
        "id": "request-1",
        "status": "processing",
        "storage_authorized_at": "now",
    }
    repository, client = _repository(SimpleNamespace(data=[authorized]))
    preflight = {"allowed": True, "available": True, "blockers": []}

    row = await repository.authorize_storage_deletion(
        _request(),
        preflight_snapshot=preflight,
    )

    assert row == authorized
    assert client.rpc_calls == [
        (
            "authorize_account_deletion_storage",
            {
                "p_request_id": "request-1",
                "p_lease_token": "lease-1",
                "p_preflight_snapshot": preflight,
            },
        )
    ]


@pytest.mark.asyncio
async def test_storage_receipt_maps_the_lease_fenced_rpc() -> None:
    repository, client = _repository(
        SimpleNamespace(data=[{"id": "request-1", "status": "processing"}])
    )

    await repository.record_storage_receipt(
        _request(),
        path="rides/user-1/ride.fit",
        outcome="confirmed_absent",
    )

    assert client.rpc_calls == [
        (
            "record_account_deletion_storage_receipt",
            {
                "p_request_id": "request-1",
                "p_lease_token": "lease-1",
                "p_path": "rides/user-1/ride.fit",
                "p_outcome": "confirmed_absent",
            },
        )
    ]


@pytest.mark.asyncio
async def test_storage_receipt_missing_durable_row_fails_closed() -> None:
    repository, _ = _repository(SimpleNamespace(data=[]))

    with pytest.raises(RuntimeError, match="returned no durable request row"):
        await repository.record_storage_receipt(
            _request(),
            path="rides/user-1/ride.fit",
            outcome="confirmed_absent",
        )


@pytest.mark.asyncio
async def test_retry_rpc_cannot_overwrite_recording_acknowledgement() -> None:
    retried = {"id": "request-1", "status": "queued"}
    repository, client = _repository(SimpleNamespace(data=[retried]))
    preflight = {"allowed": True, "available": True, "blockers": []}

    row = await repository.prepare_deletion_retry(
        "request-1",
        preflight_snapshot=preflight,
    )

    assert row == retried
    assert client.rpc_calls == [
        (
            "retry_account_deletion_request",
            {
                "p_request_id": "request-1",
                "p_preflight_snapshot": preflight,
            },
        )
    ]


def test_dead_python_storage_scanners_are_not_a_second_authority() -> None:
    assert not hasattr(ComplianceRepository, "get_user_storage_paths")
    assert not hasattr(ComplianceRepository, "get_user_storage_paths_strict")
    assert not hasattr(ComplianceRepository, "delete_user_data")
