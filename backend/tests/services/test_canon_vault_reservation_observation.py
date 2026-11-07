from __future__ import annotations

from types import SimpleNamespace

import pytest
from solders.pubkey import Pubkey

import app.services.tx_builder as tx_builder_module
from app.services.tx_builder import TxBuilder


class NewRecordBoard:
    pass


def _builder(program_id: Pubkey) -> TxBuilder:
    builder = object.__new__(TxBuilder)
    builder.rpc_url = "http://rpc.invalid"
    builder.program_id = program_id
    return builder


@pytest.mark.asyncio
async def test_finalized_absence_accepts_exact_unbound_retired_predecessor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    program_id = Pubkey.new_unique()
    commitment = bytes(range(64))
    commitment_hash = bytes(range(32))
    calls: list[str] = []

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_block_height(self, **_kwargs):
            calls.append("height")
            return SimpleNamespace(value=501)

        async def get_multiple_accounts(self, _pubkeys, **_kwargs):
            calls.append("accounts")
            return SimpleNamespace(
                value=[
                    SimpleNamespace(owner=program_id, data=b"climb-account"),
                    None,
                    None,
                ],
                context=SimpleNamespace(slot=777),
            )

    decoded = SimpleNamespace(
        name="Climb",
        data=SimpleNamespace(
            canonCommitment=commitment,
            commitmentHash=commitment_hash,
            successorClimb=Pubkey.new_unique(),
            recordContinuityPolicy=NewRecordBoard(),
            vault=Pubkey.default(),
        ),
    )
    monkeypatch.setattr(tx_builder_module, "AsyncClient", Client)
    monkeypatch.setattr(
        tx_builder_module,
        "_get_boulder_accounts_coder",
        lambda: SimpleNamespace(parse=lambda _data: decoded),
    )

    observation = await _builder(program_id).observe_finalized_canon_reservation_absence(
        climb_pda=str(Pubkey.new_unique()),
        vault_pda=str(Pubkey.new_unique()),
        vault_activation_pda=str(Pubkey.new_unique()),
        canon_commitment_hex=commitment.hex(),
        commitment_hash_hex=commitment_hash.hex(),
    )

    assert observation.slot == 777
    assert observation.block_height == 501
    assert observation.exact_source_unbound is True
    assert observation.vault_absent is True
    assert observation.activation_absent is True
    assert calls == ["height", "accounts"]


@pytest.mark.asyncio
@pytest.mark.parametrize("present_index", [1, 2])
async def test_finalized_absence_rejects_reserved_constructor_accounts(
    monkeypatch: pytest.MonkeyPatch,
    present_index: int,
) -> None:
    program_id = Pubkey.new_unique()
    accounts = [SimpleNamespace(owner=program_id, data=b"climb"), None, None]
    accounts[present_index] = SimpleNamespace(owner=program_id, data=b"exists")

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_block_height(self, **_kwargs):
            return SimpleNamespace(value=501)

        async def get_multiple_accounts(self, _pubkeys, **_kwargs):
            return SimpleNamespace(
                value=accounts,
                context=SimpleNamespace(slot=777),
            )

    monkeypatch.setattr(tx_builder_module, "AsyncClient", Client)

    with pytest.raises(ValueError, match="exists on-chain"):
        await _builder(program_id).observe_finalized_canon_reservation_absence(
            climb_pda=str(Pubkey.new_unique()),
            vault_pda=str(Pubkey.new_unique()),
            vault_activation_pda=str(Pubkey.new_unique()),
            canon_commitment_hex="11" * 64,
            commitment_hash_hex="22" * 32,
        )
