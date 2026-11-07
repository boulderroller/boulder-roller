from __future__ import annotations

import hashlib
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from solders.instruction import Instruction
from solders.keypair import Keypair
from solders.pubkey import Pubkey

import app.services.solana_submit as solana_submit
import app.solana_direct as direct
from app.solana_direct import DirectConfig, send_create_vault


def _counter_bytes(count: int) -> bytes:
    return b"counter!" + struct.pack("<Q", count) + b"\x01"


def _config(authority: Keypair) -> DirectConfig:
    return DirectConfig(
        rpc_url="http://rpc.invalid",
        program_id=Pubkey.new_unique(),
        payer=Keypair(),
        backend_authority=authority,
        dung_mint_address=Pubkey.new_unique(),
        cal_mint_address=Pubkey.new_unique(),
    )


@pytest.mark.asyncio
async def test_direct_vault_sender_wires_exact_climb_and_empty_board_pdas(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(direct, "PROGRAM_VERSION_FAMILY", "V4-A")
    authority = Keypair()
    creator = authority.pubkey()
    config = _config(authority)
    commitment = bytes(range(64))
    commitment_hash = hashlib.sha256(commitment).digest()
    expected_climb, _ = Pubkey.find_program_address(
        [b"climb", commitment_hash],
        config.program_id,
    )
    expected_vault, _ = direct._derive_vault_pda(7, config.program_id)
    expected_board, _ = direct._derive_vault_leaderboard_pda(7, config.program_id)
    expected_activation, _ = direct._derive_vault_activation_pda(7, config.program_id)
    expected_counter, _ = direct._derive_vault_counter_pda(config.program_id)

    class Client:
        def __init__(self, *_args, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        async def get_account_info(self, pubkey, **_kwargs):
            if pubkey == expected_counter:
                return SimpleNamespace(
                    value=SimpleNamespace(data=_counter_bytes(7), owner=config.program_id)
                )
            if pubkey == expected_climb:
                return SimpleNamespace(
                    value=SimpleNamespace(data=b"climb", owner=config.program_id)
                )
            return SimpleNamespace(
                value=SimpleNamespace(data=b"token", owner=Pubkey.new_unique())
            )

    instruction = Instruction(config.program_id, b"canon", [])
    maker = MagicMock(return_value=instruction)
    monkeypatch.setattr(direct, "AsyncClient", Client)
    monkeypatch.setattr(direct, "resolve_backend_authority", lambda _config: authority)
    monkeypatch.setattr(direct, "make_create_vault_ix", maker)
    submit = AsyncMock(
        return_value=SimpleNamespace(failed=False, signature="tx-signature")
    )
    monkeypatch.setattr(solana_submit, "submit_and_confirm", submit)

    common = {
        "config": config,
        "creator_wallet": str(creator),
        "signature_hex": commitment.hex(),
        "name": "Registered Climb",
        "vert_m": 10.0,
        "distance_m": 100,
        "avg_gradient_pct": 10.0,
    }
    result = await send_create_vault(**common)

    assert result["vault_id"] == 7
    kwargs = maker.call_args.kwargs
    assert kwargs["vault_counter_pda"] == expected_counter
    assert kwargs["vault_pda"] == expected_vault
    assert kwargs["climb_pda"] == expected_climb
    assert kwargs["vault_leaderboard_pda"] == expected_board
    assert kwargs["vault_activation_pda"] == expected_activation
    assert not {
        "signature",
        "name",
        "vert_m",
        "distance_m",
        "avg_gradient_pct",
    }.intersection(kwargs)
    submit.assert_awaited_once()
    signer_pubkeys = {signer.pubkey() for signer in submit.call_args.kwargs["signers"]}
    assert authority.pubkey() in signer_pubkeys


@pytest.mark.asyncio
async def test_direct_vault_sender_is_retired_before_rpc_on_v4b_even_with_rehearsal_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority = Keypair()
    config = _config(authority)

    class UnexpectedClient:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("retired V4-B sender must not touch RPC")

    monkeypatch.setattr(direct, "PROGRAM_VERSION_FAMILY", "V4-B")
    monkeypatch.setenv("BOULDER_REHEARSAL_PROGRAM_ID", str(config.program_id))
    monkeypatch.setattr(direct, "AsyncClient", UnexpectedClient)
    kwargs = {
        "config": config,
        "creator_wallet": str(authority.pubkey()),
        "signature_hex": bytes(range(64)).hex(),
        "name": "Registered Climb",
        "vert_m": 10.0,
        "distance_m": 100,
        "avg_gradient_pct": 10.0,
    }
    with pytest.raises(RuntimeError, match="prepare/submit reservation flow"):
        await send_create_vault(**kwargs)
