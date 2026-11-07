from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair

from app.services.solana_submit import (
    TxResult,
    _TxSubmissionError,
    _confirmation_status_name,
    _confirm_signature_with_retry,
    _create_lifecycle_row,
    _update_lifecycle,
    submit_and_confirm,
    transaction_evidence_guard,
)


@pytest.mark.asyncio
async def test_create_lifecycle_row_inserts_pending_tx_record():
    client = MagicMock()
    client.table.return_value.insert.return_value.execute.return_value.data = [{"id": 42}]

    with patch("app.repositories.base.get_supabase_client", return_value=client):
        lifecycle_id = await _create_lifecycle_row(
            tx_type="record_proof",
            reference_type="ride",
            reference_id="ride-123",
            wallet="wallet-abc",
            max_retries=3,
            priority_fee_lamports=10_000,
            compute_units=200_000,
            instructions_summary=[{"program_id": "prog", "accounts_count": 2, "data_len": 8}],
        )

    assert lifecycle_id == 42
    client.table.assert_called_once_with("tx_lifecycle")
    inserted_row = client.table.return_value.insert.call_args.args[0]
    assert inserted_row["tx_type"] == "record_proof"
    assert inserted_row["status"] == "pending"
    assert inserted_row["reference_type"] == "ride"
    assert inserted_row["reference_id"] == "ride-123"
    assert inserted_row["wallet"] == "wallet-abc"
    assert inserted_row["max_retries"] == 3
    assert inserted_row["priority_fee_lamports"] == 10_000
    assert inserted_row["compute_units"] == 200_000


@pytest.mark.asyncio
async def test_submit_records_requested_limit_and_ceil_rounded_priority_fee():
    payer = Keypair()
    create_lifecycle = AsyncMock(return_value=42)
    submit_attempt = AsyncMock(
        return_value=TxResult(
            success=True,
            signature="settlement-signature",
            status="finalized",
        )
    )

    with (
        patch(
            "app.services.solana_submit._create_lifecycle_row",
            new=create_lifecycle,
        ),
        patch(
            "app.services.solana_submit._submit_attempt",
            new=submit_attempt,
        ),
    ):
        result = await submit_and_confirm(
            instructions=[],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="epoch_distribute",
            compute_units=1,
            priority_fee_micro_lamports=1,
        )

    assert result.success is True
    assert create_lifecycle.await_args.kwargs["compute_units"] == 1
    assert create_lifecycle.await_args.kwargs["priority_fee_lamports"] == 1


@pytest.mark.asyncio
async def test_submit_keeps_generic_compute_default_at_200k():
    payer = Keypair()
    create_lifecycle = AsyncMock(return_value=42)
    submit_attempt = AsyncMock(
        return_value=TxResult(success=True, signature="generic", status="finalized")
    )

    with (
        patch(
            "app.services.solana_submit._create_lifecycle_row",
            new=create_lifecycle,
        ),
        patch(
            "app.services.solana_submit._submit_attempt",
            new=submit_attempt,
        ),
    ):
        await submit_and_confirm(
            instructions=[],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="record_proof",
        )

    assert create_lifecycle.await_args.kwargs["compute_units"] == 200_000


@pytest.mark.asyncio
async def test_rehearsal_evidence_guard_disables_production_lifecycle_writes():
    payer = Keypair()
    create_lifecycle = AsyncMock(return_value=42)
    submit_attempt = AsyncMock(
        return_value=TxResult(success=True, signature="local", status="finalized")
    )
    guard = SimpleNamespace(
        record_prepared_transaction=lambda *args, **kwargs: None,
        record_finalized_transaction=lambda *args, **kwargs: None,
    )

    with (
        transaction_evidence_guard(guard),
        patch(
            "app.services.solana_submit._create_lifecycle_row",
            new=create_lifecycle,
        ),
        patch(
            "app.services.solana_submit._submit_attempt",
            new=submit_attempt,
        ),
    ):
        result = await submit_and_confirm(
            instructions=[],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="rehearsal",
        )

    assert result.success is True
    create_lifecycle.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("compute_units", "priority_fee", "message"),
    [
        (-1, 1, "compute unit limit"),
        (1_400_001, 1, "compute unit limit"),
        (200_000, -1, "priority fee"),
        (0, 1, "priority fee requires"),
    ],
)
async def test_submit_rejects_invalid_compute_budget_configuration(
    compute_units,
    priority_fee,
    message,
):
    payer = Keypair()
    submit_attempt = AsyncMock(
        return_value=TxResult(success=True, signature="unexpected", status="finalized")
    )

    with (
        patch(
            "app.services.solana_submit._submit_attempt",
            new=submit_attempt,
        ),
        pytest.raises(ValueError, match=message),
    ):
        await submit_and_confirm(
            instructions=[],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="epoch_distribute",
            compute_units=compute_units,
            priority_fee_micro_lamports=priority_fee,
            skip_lifecycle=True,
        )

    submit_attempt.assert_not_awaited()


@pytest.mark.asyncio
async def test_update_lifecycle_updates_existing_tx_record():
    client = MagicMock()

    with patch("app.repositories.base.get_supabase_client", return_value=client):
        await _update_lifecycle(42, status="submitted", signature="sig-123", retry_count=1)

    client.table.assert_called_once_with("tx_lifecycle")
    client.table.return_value.update.assert_called_once_with(
        {"status": "submitted", "signature": "sig-123", "retry_count": 1}
    )
    client.table.return_value.update.return_value.eq.assert_called_once_with("id", 42)


@pytest.mark.asyncio
async def test_update_lifecycle_skips_when_tracking_disabled():
    client = MagicMock()

    with patch("app.repositories.base.get_supabase_client", return_value=client):
        await _update_lifecycle(None, status="submitted")

    client.table.assert_not_called()


@pytest.mark.asyncio
async def test_confirm_signature_retries_transient_rpc_errors():
    class FakeClient:
        def __init__(self):
            self.calls = 0

        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            self.calls += 1
            if self.calls == 1:
                raise Exception("429 Too Many Requests")
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err=None,
                        slot=123,
                        confirmation_status="finalized",
                    )
                ]
            )

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

    with patch("app.services.solana_submit.asyncio.sleep", return_value=None):
        status = await _confirm_signature_with_retry(
            client=FakeClient(),
            signature=MagicMock(),
            commitment_obj=MagicMock(),
            commitment_str="finalized",
            last_valid_block_height=100,
            tx_type="epoch_distribute",
        )

    assert status.slot == 123


@pytest.mark.asyncio
async def test_confirm_signature_raises_transaction_error():
    class FakeClient:
        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err="custom program error",
                        slot=123,
                        confirmation_status="confirmed",
                    )
                ]
            )

    with pytest.raises(_TxSubmissionError, match="custom program error"):
        await _confirm_signature_with_retry(
            client=FakeClient(),
            signature=MagicMock(),
            commitment_obj=MagicMock(),
            commitment_str="confirmed",
            last_valid_block_height=100,
            tx_type="record_completion",
        )


@pytest.mark.asyncio
async def test_expired_height_searches_history_before_declaring_signature_missing():
    class FakeClient:
        def __init__(self):
            self.search_history: list[bool] = []

        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            self.search_history.append(search_transaction_history)
            if not search_transaction_history:
                return SimpleNamespace(value=[None])
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err=None,
                        slot=456,
                        confirmation_status="confirmed",
                    )
                ]
            )

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=101)

    client = FakeClient()
    status = await _confirm_signature_with_retry(
        client=client,
        signature=MagicMock(),
        commitment_obj=MagicMock(),
        commitment_str="confirmed",
        last_valid_block_height=100,
        tx_type="wallet_signed",
    )

    assert status.slot == 456
    assert client.search_history == [False, True]


def test_confirmation_status_name_handles_solders_enum_string():
    status = SimpleNamespace(confirmation_status="TransactionConfirmationStatus.Finalized")

    assert _confirmation_status_name(status) == "finalized"


@pytest.mark.asyncio
async def test_accepted_signature_callback_precedes_stalled_confirmation_when_lifecycle_fails():
    events: list[str] = []
    payer = Keypair()

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_latest_blockhash(self):
            return SimpleNamespace(
                value=SimpleNamespace(
                    blockhash=Hash.default(),
                    last_valid_block_height=100,
                )
            )

        async def send_raw_transaction(self, _tx):
            events.append("rpc-accepted")
            return SimpleNamespace(value="accepted-signature")

    async def persist_signature(signature: str) -> None:
        assert events == ["rpc-accepted"]
        events.append(f"job-persisted:{signature}")

    async def stalled_confirmation(**_kwargs):
        assert events[-1] == "job-persisted:accepted-signature"
        events.append("confirmation-stalled")
        raise RuntimeError("confirmation stalled")

    lifecycle_client = MagicMock()
    lifecycle_client.table.return_value.update.return_value.eq.return_value.execute.side_effect = (
        RuntimeError("tx_lifecycle unavailable")
    )

    with patch("app.services.solana_submit.AsyncClient", FakeClient):
        with patch(
            "app.services.solana_submit._create_lifecycle_row",
            new=AsyncMock(return_value=42),
        ):
            with patch(
                "app.services.solana_submit._confirm_signature_with_retry",
                side_effect=stalled_confirmation,
            ):
                with patch(
                    "app.repositories.base.get_supabase_client",
                    return_value=lifecycle_client,
                ):
                    result = await submit_and_confirm(
                        instructions=[],
                        signers=[payer],
                        fee_payer=payer.pubkey(),
                        tx_type="epoch_distribute",
                        commitment="finalized",
                        on_submitted=persist_signature,
                    )

    assert result.success is False
    assert result.status == "submitted"
    assert result.signature == "accepted-signature"
    assert events == [
        "rpc-accepted",
        "job-persisted:accepted-signature",
        "confirmation-stalled",
    ]


@pytest.mark.asyncio
async def test_failed_accepted_signature_callback_stops_confirmation_and_retry():
    payer = Keypair()
    sends = 0
    confirm = AsyncMock()

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_latest_blockhash(self):
            return SimpleNamespace(
                value=SimpleNamespace(
                    blockhash=Hash.default(),
                    last_valid_block_height=100,
                )
            )

        async def send_raw_transaction(self, _tx):
            nonlocal sends
            sends += 1
            return SimpleNamespace(value="accepted-signature")

    async def fail_persistence(_signature: str) -> None:
        raise RuntimeError("settlement database unavailable")

    with patch("app.services.solana_submit.AsyncClient", FakeClient):
        with patch(
            "app.services.solana_submit._confirm_signature_with_retry",
            confirm,
        ):
            result = await submit_and_confirm(
                instructions=[],
                signers=[payer],
                fee_payer=payer.pubkey(),
                tx_type="epoch_distribute",
                commitment="finalized",
                skip_lifecycle=True,
                on_submitted=fail_persistence,
            )

    assert result.success is False
    assert result.status == "accepted_ambiguous"
    assert result.signature == "accepted-signature"
    assert sends == 1
    confirm.assert_not_awaited()


@pytest.mark.asyncio
async def test_send_response_loss_reconciles_prepared_signature_without_resend():
    payer = Keypair()
    sends = 0
    prepared: list[str] = []
    accepted = AsyncMock()

    class FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_latest_blockhash(self):
            return SimpleNamespace(
                value=SimpleNamespace(
                    blockhash=Hash.default(),
                    last_valid_block_height=100,
                )
            )

        async def send_raw_transaction(self, _tx):
            nonlocal sends
            sends += 1
            raise TimeoutError("RPC accepted bytes but response was lost")

    async def persist_prepared(signature: str) -> None:
        prepared.append(signature)

    with patch("app.services.solana_submit.AsyncClient", FakeClient):
        result = await submit_and_confirm(
            instructions=[],
            signers=[payer],
            fee_payer=payer.pubkey(),
            tx_type="epoch_distribute",
            commitment="finalized",
            max_retries=3,
            skip_lifecycle=True,
            on_prepared=persist_prepared,
            on_submitted=accepted,
        )

    assert result.success is False
    assert result.status == "prepared_ambiguous"
    assert result.signature == prepared[0]
    assert sends == 1
    accepted.assert_not_awaited()
