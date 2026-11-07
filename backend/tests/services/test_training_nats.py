"""The deployed NATS entry point scores synthetic rides after payment/ACK."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock
from uuid import UUID

import pytest

from backend.tests.services.test_nats_consumer_ride_ingest import (
    FakeNatsMessage,
    _uploaded_payload,
)
from backend.tests.services.test_training_pipeline import Repo, parsed
from app.services import nats_consumer, file_storage, workout_parse_adapter


@pytest.mark.asyncio
@pytest.mark.parametrize("slow_finish", [False, True])
async def test_pay_latency_is_independent_of_training_database(
    monkeypatch, slow_finish
):
    from app import repositories
    from app.services.training_runtime import TrainingReplayRuntime

    db_entered, release_db = asyncio.Event(), asyncio.Event()
    pay_entered, finish_pay = asyncio.Event(), asyncio.Event()

    async def record(ride_id, user_id, token, finished):
        if finished == slow_finish:
            db_entered.set()
            await release_db.wait()

    async def pay(msg, payload):
        pay_entered.set()
        await finish_pay.wait()
        await msg.ack()

    runtime = TrainingReplayRuntime()
    monkeypatch.setattr(
        repositories,
        "create_ride_repository",
        lambda: SimpleNamespace(set_training_pay_attempt=record),
    )
    monkeypatch.setattr(nats_consumer, "_training_runtime", runtime)
    monkeypatch.setattr(nats_consumer, "_handle_uploaded", pay)
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    upload = asyncio.create_task(nats_consumer._handle_message(msg))
    try:
        # No database completion is needed to enter pay or return from its ACK.
        await asyncio.wait_for(pay_entered.wait(), 0.2)
        finish_pay.set()
        await asyncio.wait_for(asyncio.shield(upload), 0.2)
        await asyncio.wait_for(db_entered.wait(), 0.2)
        assert not release_db.is_set()
        msg.ack.assert_awaited_once()
        msg.nak.assert_not_awaited()
        assert runtime.blocked_rides == {payload["ride_id"]}
    finally:
        finish_pay.set()
        release_db.set()
        await asyncio.gather(upload, return_exceptions=True)
        await runtime.stop()


@pytest.mark.asyncio
@pytest.mark.parametrize("ride_id", [[], {}, "not-a-uuid"])
async def test_malformed_upload_cannot_poison_training_claims(monkeypatch, ride_id):
    from app import repositories
    from app.services.training_runtime import TrainingReplayRuntime

    repo = SimpleNamespace(set_training_pay_attempt=AsyncMock())
    monkeypatch.setattr(repositories, "create_ride_repository", lambda: repo)
    runtime = TrainingReplayRuntime()
    monkeypatch.setattr(nats_consumer, "_training_runtime", runtime)
    msg = FakeNatsMessage(
        "rides.events.uploaded", {**_uploaded_payload(), "ride_id": ride_id}
    )
    await nats_consumer._handle_message(msg)
    msg.ack.assert_awaited_once()
    msg.nak.assert_not_awaited()
    assert runtime.blocked_rides == set()
    valid = _uploaded_payload()
    token = runtime.begin_attempt(valid)
    assert token is not None
    assert all(UUID(value) for value in runtime.blocked_rides)
    runtime.finish_attempt(valid, token)
    await asyncio.gather(*runtime._receipt_tasks)
    assert runtime.blocked_rides == set()


@pytest.mark.asyncio
@pytest.mark.parametrize("begin_fails", [False, True])
async def test_queued_receipts_keep_attempt_order_and_fail_closed(
    monkeypatch, begin_fails
):
    from app import repositories
    from app.services.training_runtime import TrainingReplayRuntime

    entered, release = asyncio.Event(), asyncio.Event()
    calls = []

    async def record(ride_id, user_id, token, finished):
        calls.append((token, finished))
        if len(calls) == 1:
            entered.set()
            await release.wait()
            if begin_fails:
                raise RuntimeError("synthetic boundary failure")
        assert ride_id in runtime.blocked_rides

    monkeypatch.setattr(
        repositories,
        "create_ride_repository",
        lambda: SimpleNamespace(set_training_pay_attempt=record),
    )
    runtime = TrainingReplayRuntime()
    payload = _uploaded_payload()
    first = runtime.begin_attempt(payload)
    await entered.wait()
    second = runtime.begin_attempt(payload)
    runtime.finish_attempt(payload, first)
    runtime.finish_attempt(payload, second)
    await asyncio.sleep(0)
    assert calls == [(first, False)]
    release.set()
    await asyncio.gather(*runtime._receipt_tasks)
    if begin_fails:
        assert calls == [(first, False)]
        assert runtime.blocked_rides == {payload["ride_id"]}
    else:
        assert calls == [(first, False), (second, False), (first, True), (second, True)]
        assert runtime.blocked_rides == set()
        assert runtime._receipt_tail == {}
    await runtime.stop()


@pytest.mark.asyncio
async def test_shutdown_prevents_late_upload_receipts(monkeypatch):
    from app import repositories
    from app.services.training_runtime import TrainingReplayRuntime

    entered = asyncio.Event()

    async def record(*args):
        entered.set()
        await asyncio.Event().wait()

    call = AsyncMock(side_effect=record)
    monkeypatch.setattr(
        repositories,
        "create_ride_repository",
        lambda: SimpleNamespace(set_training_pay_attempt=call),
    )
    runtime = TrainingReplayRuntime()
    payload = _uploaded_payload()
    token = runtime.begin_attempt(payload)
    await entered.wait()
    await runtime.stop()
    runtime.finish_attempt(payload, token)
    assert runtime.begin_attempt(payload) is None
    assert not runtime._receipt_tasks
    call.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("score_fails", [False, True])
@pytest.mark.parametrize("pay_failure", [None, "phase2", "phase3"])
async def test_production_consumer_scores_new_upload_after_pay_and_ack(
    monkeypatch, score_fails, pay_failure
):
    from app import repositories

    order, ready = [], []
    caught_up, finished = asyncio.Event(), asyncio.Event()
    repo = Repo()
    repo.client = object()
    payload = _uploaded_payload()
    ride = {
        "id": payload["ride_id"],
        "user_id": payload["user_id"],
        "started_at": "2026-10-08T01:00:00Z",
        "raw_file_path": "synthetic.fit",
        "processing_status": "processing",
    }
    expected_pay = ["phase1", "phase2"]
    if pay_failure != "phase2":
        expected_pay.append("phase3")
    expected_pay.append("nak" if pay_failure else "ack")

    async def track(ride_id, user_id, token, finished):
        if finished:
            assert order == expected_pay
            ready.append(ride)

    repo.set_training_pay_attempt = track
    repo.training_replay_startup_cutoff = AsyncMock(return_value="2026-10-08T00:00:00Z")

    async def claim(limit):
        assert limit == 10
        caught_up.set()
        batch = ready[:]
        ready.clear()
        return batch

    async def finish(*args, scoring_inputs=None):
        order.append("training_failed" if args[-1] else "training_stored")
        finished.set()

    original_bind = repo.bind_training_inputs

    async def bind(*args):
        assert order[: len(expected_pay)] == expected_pay
        if score_fails:
            raise ValueError("synthetic scoring failure")
        return await original_bind(*args)

    repo.claim_training_replay, repo.finish_training_replay = claim, finish
    repo.bind_training_inputs = bind
    monkeypatch.setattr(repositories, "create_ride_repository", lambda: repo)
    monkeypatch.setattr(
        workout_parse_adapter, "parse_ride_file_bytes_rust", lambda *args: parsed()
    )
    monkeypatch.setattr(file_storage.FileStorageService, "__init__", lambda *args: None)
    monkeypatch.setattr(
        file_storage.FileStorageService,
        "download_ride_file",
        AsyncMock(return_value=b"synthetic"),
    )
    monkeypatch.setattr(
        file_storage,
        "create_file_storage_service",
        lambda: file_storage.FileStorageService(),
    )
    client = AsyncMock()
    monkeypatch.setattr(nats_consumer, "get_nats_client", lambda: client)
    monkeypatch.setattr(nats_consumer, "close_nats_client", AsyncMock())

    async def idle():
        await asyncio.Event().wait()

    monkeypatch.setattr(nats_consumer, "_stale_ride_cleanup_loop", idle)
    recovery = AsyncMock()
    recovery.run_forever.side_effect = idle
    monkeypatch.setattr(
        nats_consumer, "_create_ride_economic_recovery_loop", lambda: recovery
    )
    processor = AsyncMock()

    def phase(name, status):
        async def run(**kwargs):
            order.append(name)
            if name == pay_failure:
                raise ValueError("synthetic payment failure")
            ride["processing_status"] = "completed" if status == "complete" else status
            return {"status": status}

        return run

    processor.process_phase1_core.side_effect = phase("phase1", "metrics_ready")
    processor.process_phase2_enrichment.side_effect = phase("phase2", "enriched")
    processor.process_phase3_rewards.side_effect = phase("phase3", "complete")
    monkeypatch.setattr(nats_consumer, "_get_processor", lambda: processor)
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    msg.ack.side_effect = lambda: order.append("ack")
    msg.nak.side_effect = lambda **kwargs: order.append("nak")
    try:
        await nats_consumer.start_consumer()
        await asyncio.wait_for(caught_up.wait(), 1)  # catch-up starts without an event
        handler = client.subscribe.call_args_list[0].kwargs["handler"]
        await handler(msg)
        await asyncio.wait_for(finished.wait(), 2)  # wake, not the 60-second poll
        assert order == expected_pay + [
            "training_failed" if score_fails else "training_stored"
        ]
        assert msg.ack.await_count == (0 if pay_failure else 1)
        assert msg.nak.await_count == (1 if pay_failure else 0)
        for method in (
            processor.process_phase1_core,
            processor.process_phase2_enrichment,
        ):
            assert method.await_count == 1
        assert processor.process_phase3_rewards.await_count == (
            0 if pay_failure == "phase2" else 1
        )
        if not score_fails:
            assert repo.metrics[ride["id"]]["load"] == 32
        task = nats_consumer._training_runtime.task
    finally:
        await nats_consumer.stop_consumer()
    assert task.done()


@pytest.mark.asyncio
@pytest.mark.parametrize("boundary", ["begin", "finish"])
@pytest.mark.parametrize("pay_fails", [False, True])
async def test_receipt_failure_preserves_pay_ack_or_nak(
    monkeypatch, caplog, boundary, pay_fails
):
    from app import repositories
    from app.services.training_runtime import TrainingReplayRuntime

    async def record(ride_id, user_id, token, finished):
        if finished == (boundary == "finish"):
            raise RuntimeError("private database message")

    repo = SimpleNamespace(set_training_pay_attempt=record)
    monkeypatch.setattr(repositories, "create_ride_repository", lambda: repo)
    runtime = TrainingReplayRuntime()
    monkeypatch.setattr(nats_consumer, "_training_runtime", runtime)

    async def pay(msg, payload):
        if pay_fails:
            await msg.nak()
        else:
            await msg.ack()

    handler = AsyncMock(side_effect=pay)
    monkeypatch.setattr(nats_consumer, "_handle_uploaded", handler)
    payload = _uploaded_payload()
    msg = FakeNatsMessage("rides.events.uploaded", payload)
    await nats_consumer._handle_message(msg)
    await asyncio.gather(*runtime._receipt_tasks)
    handler.assert_awaited_once()
    assert msg.ack.await_count == (0 if pay_fails else 1)
    assert msg.nak.await_count == (1 if pay_fails else 0)
    assert runtime.blocked_rides == {payload["ride_id"]}
    assert "private database message" not in caplog.text


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["exception", "timeout"])
async def test_training_runtime_retries_failed_pass_without_overlap_and_stops(
    monkeypatch, failure, caplog
):
    from app.services import training_runtime
    from app import repositories

    monkeypatch.setattr(repositories, "create_ride_repository", SimpleNamespace)
    finished = asyncio.Event()
    calls = active = peak = 0

    async def batch(repo, *, limit):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        assert limit == 10
        try:
            if calls == 1:
                if failure == "exception":
                    raise ValueError("private file content")
                await asyncio.Event().wait()
            finished.set()
        finally:
            active -= 1

    monkeypatch.setattr(training_runtime, "replay_training_batch", batch)
    runtime = training_runtime.TrainingReplayRuntime(
        interval_s=0.01, pass_timeout_s=0.01
    )
    runtime.start()
    task = runtime.task
    try:
        await asyncio.wait_for(finished.wait(), 1)
    finally:
        await runtime.stop()
    assert peak == 1 and calls == 2 and active == 0
    assert task.done() and runtime.task is None
    assert "private file content" not in caplog.text


@pytest.mark.asyncio
async def test_scoring_computation_does_not_run_on_payment_event_loop(monkeypatch):
    import threading
    from app.services import training_metrics, climb_read_metrics

    loop_thread = threading.get_ident()
    checked = []

    def off_loop(function):
        def wrapped(*args, **kwargs):
            assert threading.get_ident() != loop_thread
            checked.append(function.__name__)
            return function(*args, **kwargs)

        return wrapped

    for module, name in [
        (training_metrics, "evidence_for"),
        (training_metrics, "compute"),
        (climb_read_metrics, "retained_climb_reads"),
    ]:
        monkeypatch.setattr(module, name, off_loop(getattr(module, name)))
    result = await training_metrics.TrainingMetricsService(Repo()).score(
        ride_id="r", user_id="u", parsed_ride=parsed()
    )
    assert result["load"] == 32
    assert checked == ["evidence_for", "compute", "retained_climb_reads"]
