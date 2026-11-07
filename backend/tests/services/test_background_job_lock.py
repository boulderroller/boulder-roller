from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.services.background_job_lock import BackgroundJobLock


@dataclass
class FakeResponse:
    data: object


class FakeRpcCall:
    def __init__(self, client: "FakeClient", fn_name: str, params: dict):
        self._client = client
        self._fn_name = fn_name
        self._params = params

    def execute(self) -> FakeResponse:
        self._client.calls.append((self._fn_name, self._params))
        response = self._client.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return FakeResponse(response)


class FakeClient:
    def __init__(self, responses: list[object]):
        self.responses = list(responses)
        self.calls: list[tuple[str, dict]] = []

    def rpc(self, fn_name: str, params: dict) -> FakeRpcCall:
        return FakeRpcCall(self, fn_name, params)


@pytest.mark.asyncio
async def test_background_job_lock_acquire_and_release():
    client = FakeClient([True, True])
    lock = BackgroundJobLock(client, "epoch_processor", ttl_seconds=120, owner_id="owner-1")

    acquired = await lock.acquire()
    released = await lock.release()

    assert acquired is True
    assert released is True
    assert client.calls == [
        (
            "acquire_background_job_lock",
            {
                "p_job_name": "epoch_processor",
                "p_owner_id": "owner-1",
                "p_ttl_seconds": 120,
            },
        ),
        (
            "release_background_job_lock",
            {
                "p_job_name": "epoch_processor",
                "p_owner_id": "owner-1",
            },
        ),
    ]


@pytest.mark.asyncio
async def test_background_job_lock_handles_dict_rpc_results():
    client = FakeClient([{"acquired": True}, {"released": True}])
    lock = BackgroundJobLock(client, "epoch_processor", owner_id="owner-2")

    assert await lock.acquire() is True
    assert await lock.release() is True


@pytest.mark.asyncio
async def test_background_job_lock_falls_back_when_migration_missing():
    client = FakeClient(
        [RuntimeError("Could not find the function public.acquire_background_job_lock")]
    )
    lock = BackgroundJobLock(client, "background_health_probe", owner_id="owner-3")

    assert await lock.acquire() is True
    assert await lock.release() is False
    assert client.calls == [
        (
            "acquire_background_job_lock",
            {
                "p_job_name": "background_health_probe",
                "p_owner_id": "owner-3",
                "p_ttl_seconds": 900,
            },
        )
    ]
