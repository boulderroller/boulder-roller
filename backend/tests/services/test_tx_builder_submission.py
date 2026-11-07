from __future__ import annotations

import base64
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from solders.hash import Hash
from solders.keypair import Keypair
from solders.transaction import Transaction

from app.services.tx_builder import (
    SubmittedTransactionExpired,
    SubmittedTransactionFailed,
    SubmittedTransactionPending,
    TxBuilder,
)
from app.services.solana_submit import (
    TransactionConfirmationTimeout,
    transaction_evidence_guard,
)


def _signed_transaction() -> tuple[str, str]:
    payer = Keypair()
    tx = Transaction.new_signed_with_payer(
        [],
        payer.pubkey(),
        [payer],
        Hash.new_unique(),
    )
    return base64.b64encode(bytes(tx)).decode("ascii"), str(tx.signatures[0])


def _builder() -> TxBuilder:
    builder = object.__new__(TxBuilder)
    builder.rpc_url = "http://solana.invalid"
    return builder


class _ClientContext:
    def __init__(self, *_args, **_kwargs) -> None:
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None


class _EvidenceGuard:
    def __init__(self) -> None:
        self.prepared: list[dict] = []
        self.finalized: list[tuple] = []
        self.terminal: list[tuple] = []

    def record_prepared_transaction(self, transaction, lookup_tables, metadata) -> None:
        self.prepared.append(dict(metadata))

    def record_finalized_transaction(self, signature, slot, status, metadata) -> None:
        self.finalized.append((signature, slot, status, dict(metadata)))

    def record_terminal_transaction(self, signature, status, metadata) -> None:
        self.terminal.append((signature, status, dict(metadata)))


@pytest.mark.asyncio
async def test_submit_rejects_confirmed_signature_with_chain_error() -> None:
    transaction_b64, signature = _signed_transaction()

    class FakeClient(_ClientContext):
        def __init__(self, *_args, **_kwargs) -> None:
            self.status_calls = 0

        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            self.status_calls += 1
            if self.status_calls == 1:
                return SimpleNamespace(value=[None])
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err="custom program error: 0x1770",
                        slot=12,
                        confirmation_status="confirmed",
                    )
                ]
            )

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=True)

        async def send_raw_transaction(self, _transaction):
            return SimpleNamespace(value=signature)

    guard = _EvidenceGuard()
    with (
        patch("app.services.tx_builder.AsyncClient", FakeClient),
        transaction_evidence_guard(guard),
        pytest.raises(SubmittedTransactionFailed, match="custom program error"),
    ):
        await _builder().submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=100,
        )
    assert guard.terminal[0][1] == "failed"


@pytest.mark.asyncio
async def test_submit_expires_unseen_signature_before_sending_stale_bytes() -> None:
    transaction_b64, _ = _signed_transaction()

    class FakeClient(_ClientContext):
        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            return SimpleNamespace(value=[None])

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=101)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=False)

        async def send_raw_transaction(self, _transaction):
            raise AssertionError("expired transaction bytes must not be sent")

    guard = _EvidenceGuard()
    with (
        patch("app.services.tx_builder.AsyncClient", FakeClient),
        transaction_evidence_guard(guard),
        pytest.raises(SubmittedTransactionExpired, match="expired"),
    ):
        await _builder().submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=100,
        )
    assert guard.prepared[0]["last_valid_block_height"] == 100
    assert guard.terminal[0][1] == "expired"


@pytest.mark.asyncio
async def test_submit_checks_blockhash_with_pinned_client_without_public_helper() -> None:
    transaction_b64, _ = _signed_transaction()

    class FakeProvider:
        async def make_request(self, request, response_type):
            assert request.to_json().startswith('{"method":"isBlockhashValid"')
            assert response_type.__name__ == "IsBlockhashValidResp"
            return SimpleNamespace(value=False)

    class FakeClient(_ClientContext):
        def __init__(self, *_args, **_kwargs) -> None:
            self._provider = FakeProvider()

        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            return SimpleNamespace(value=[None])

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def send_raw_transaction(self, _transaction):
            raise AssertionError("an invalid blockhash must not be sent")

    with patch("app.services.tx_builder.AsyncClient", FakeClient):
        with pytest.raises(SubmittedTransactionExpired, match="expired"):
            await _builder().submit_signed_transaction(
                transaction_b64,
                last_valid_block_height=100,
            )


@pytest.mark.asyncio
async def test_submit_reconciles_signed_signature_after_send_response_loss() -> None:
    transaction_b64, signature = _signed_transaction()

    class FakeClient(_ClientContext):
        def __init__(self, *_args, **_kwargs) -> None:
            self.status_calls = 0

        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            self.status_calls += 1
            if self.status_calls == 1:
                return SimpleNamespace(value=[None])
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err=None,
                        slot=99,
                        confirmation_status="confirmed",
                    )
                ]
            )

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=True)

        async def send_raw_transaction(self, _transaction):
            raise TimeoutError("RPC response lost")

    with patch("app.services.tx_builder.AsyncClient", FakeClient):
        result = await _builder().submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=100,
        )

    assert result == signature


@pytest.mark.asyncio
async def test_submit_reuses_existing_confirmed_signature_without_resend() -> None:
    transaction_b64, signature = _signed_transaction()

    class FakeClient(_ClientContext):
        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            return SimpleNamespace(
                value=[
                    SimpleNamespace(
                        err=None,
                        slot=120,
                        confirmation_status="confirmed",
                    )
                ]
            )

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=True)

        async def send_raw_transaction(self, _transaction):
            raise AssertionError("a confirmed signature must not be sent again")

    with patch("app.services.tx_builder.AsyncClient", FakeClient):
        result = await _builder().submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=100,
        )

    assert result == signature


@pytest.mark.asyncio
async def test_submit_stops_on_structured_preflight_failure() -> None:
    transaction_b64, _ = _signed_transaction()

    class FakeClient(_ClientContext):
        async def get_signature_statuses(self, signatures, search_transaction_history=False):
            return SimpleNamespace(value=[None])

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=True)

        async def send_raw_transaction(self, _transaction):
            failure = SimpleNamespace(data=SimpleNamespace(err="insufficient funds"))
            raise RuntimeError(failure)

    with patch("app.services.tx_builder.AsyncClient", FakeClient):
        with pytest.raises(SubmittedTransactionFailed, match="insufficient funds"):
            await _builder().submit_signed_transaction(
                transaction_b64,
                last_valid_block_height=100,
            )


@pytest.mark.asyncio
async def test_guarded_confirmation_timeout_stays_pending_not_terminal() -> None:
    transaction_b64, signature = _signed_transaction()

    class FakeClient(_ClientContext):
        async def get_signature_statuses(self, *args, **kwargs):
            return SimpleNamespace(value=[None])

        async def get_block_height(self, commitment=None):
            return SimpleNamespace(value=10)

        async def is_blockhash_valid(self, blockhash, commitment=None):
            return SimpleNamespace(value=True)

        async def send_raw_transaction(self, _transaction):
            return SimpleNamespace(value=signature)

    guard = _EvidenceGuard()
    with (
        patch("app.services.tx_builder.AsyncClient", FakeClient),
        patch(
            "app.services.tx_builder.confirm_signature_with_retry",
            side_effect=TransactionConfirmationTimeout("unknown pending"),
        ),
        transaction_evidence_guard(guard),
        pytest.raises(SubmittedTransactionPending, match="pending"),
    ):
        await _builder().submit_signed_transaction(
            transaction_b64,
            last_valid_block_height=100,
        )
    assert len(guard.prepared) == 1
    assert guard.terminal == []
