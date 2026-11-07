from __future__ import annotations

import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from solders.keypair import Keypair
from solders.pubkey import Pubkey

from app.solana_direct import (
    DEFAULT_BOULDER_PROGRAM_ID,
    TOKEN_PROGRAM_ID,
    _account_discriminator,
    _decode_rider_balance_header,
    _derive_program_config_pda,
    _derive_rider_balance_auth_pda,
    _derive_rider_balance_pda,
    _derive_rider_balance_token_pda,
    get_rider_balance_account_snapshot,
)


@pytest.fixture(autouse=True)
def isolate_program_version_observations(monkeypatch):
    from app import program_compatibility, solana_direct
    monkeypatch.setattr(program_compatibility, "_networks", {})
    # Balance tests isolate persistence; the cutover runtime tests use Postgres.
    async def observe(_client, rpc_url, program, version):
        state = program_compatibility.program_compatibility(rpc_url, program)
        state.observe(version)
        return state
    monkeypatch.setattr(solana_direct, "observe_program_version", observe)


def _rider_balance_data(
    *,
    rider: Pubkey,
    status: int,
    bump: int,
    authority_model: int = 0,
    last_rotation_at: int = 1_720_000_000,
    revoked_at: int = 0,
) -> bytes:
    return b"".join(
        (
            _account_discriminator("RiderBalance"),
            bytes(rider),
            bytes((status, authority_model)),
            bytes(range(32)),
            bytes(Pubkey.default()),
            struct.pack("<qqB", last_rotation_at, revoked_at, bump),
        )
    )


def _token_account_data(*, mint: Pubkey, owner: Pubkey, amount: int) -> bytes:
    data = bytearray(165)
    data[0:32] = bytes(mint)
    data[32:64] = bytes(owner)
    struct.pack_into("<Q", data, 64, amount)
    data[108] = 1
    return bytes(data)


def _account(*, owner: Pubkey, data: bytes) -> SimpleNamespace:
    return SimpleNamespace(owner=owner, data=data)


def _rpc_client(*, bootstrap, snapshot):
    client = AsyncMock()
    client.get_account_info = AsyncMock(return_value=bootstrap)
    client.get_multiple_accounts = AsyncMock(return_value=snapshot)
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)
    return client


@pytest.mark.parametrize(
    ("status_byte", "expected_status", "revoked_at"),
    (
        (0, "active", 0),
        (1, "locked", 0),
        (2, "recovering", 0),
        (3, "revoked", 1_720_000_100),
    ),
)
def test_rider_balance_header_uses_current_idl_layout(
    status_byte: int,
    expected_status: str,
    revoked_at: int,
) -> None:
    rider = Keypair().pubkey()
    _, bump = _derive_rider_balance_pda(rider, DEFAULT_BOULDER_PROGRAM_ID)

    decoded = _decode_rider_balance_header(
        _rider_balance_data(
            rider=rider,
            status=status_byte,
            bump=bump,
            revoked_at=revoked_at,
        ),
        expected_rider=rider,
        expected_bump=bump,
    )

    assert decoded["rider"] == str(rider)
    assert decoded["status"] == expected_status
    assert decoded["authority_model"] == "app_balance"
    assert decoded["policy_hash"] == bytes(range(32)).hex()
    assert decoded["last_authority_rotation_at"] == 1_720_000_000
    assert decoded["revoked_at"] == revoked_at
    assert decoded["bump"] == bump


def test_rider_balance_header_rejects_wrong_rider_or_bump() -> None:
    rider = Keypair().pubkey()
    other_rider = Keypair().pubkey()
    _, bump = _derive_rider_balance_pda(rider, DEFAULT_BOULDER_PROGRAM_ID)
    data = _rider_balance_data(rider=other_rider, status=0, bump=bump)

    with pytest.raises(ValueError, match="rider"):
        _decode_rider_balance_header(
            data,
            expected_rider=rider,
            expected_bump=bump,
        )

    data = _rider_balance_data(rider=rider, status=0, bump=(bump + 1) % 256)
    with pytest.raises(ValueError, match="bump"):
        _decode_rider_balance_header(
            data,
            expected_rider=rider,
            expected_bump=bump,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("program_version", [0x4C, 0x4D])
async def test_balance_snapshot_reads_header_cal_and_usdc_from_their_own_pdas(program_version: int) -> None:
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    config_pda, _ = _derive_program_config_pda(DEFAULT_BOULDER_PROGRAM_ID)
    header_pda, header_bump = _derive_rider_balance_pda(
        rider,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    balance_authority, _ = _derive_rider_balance_auth_pda(
        rider,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    cal_pda, _ = _derive_rider_balance_token_pda(
        rider,
        cal_mint,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    usdc_pda, _ = _derive_rider_balance_token_pda(
        rider,
        usdc_mint,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    cal_amount = 9_007_199_254_740_993
    usdc_amount = 18_014_398_509_481_987
    config_account = _account(owner=DEFAULT_BOULDER_PROGRAM_ID, data=b"config")
    bootstrap = SimpleNamespace(context=SimpleNamespace(slot=440), value=config_account)
    snapshot = SimpleNamespace(
        context=SimpleNamespace(slot=441),
        value=[
            config_account,
            _account(
                owner=DEFAULT_BOULDER_PROGRAM_ID,
                data=_rider_balance_data(
                    rider=rider,
                    status=2,
                    bump=header_bump,
                ),
            ),
            _account(
                owner=TOKEN_PROGRAM_ID,
                data=_token_account_data(
                    mint=cal_mint,
                    owner=balance_authority,
                    amount=cal_amount,
                ),
            ),
            _account(
                owner=TOKEN_PROGRAM_ID,
                data=_token_account_data(
                    mint=usdc_mint,
                    owner=balance_authority,
                    amount=usdc_amount,
                ),
            ),
        ],
    )
    client = _rpc_client(bootstrap=bootstrap, snapshot=snapshot)
    decoded_config = {
        "initialized": True,
        "program_version": program_version,
        "cal_mint": str(cal_mint),
        "usdc_mint": str(usdc_mint),
    }

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_program_config_account",
            return_value=decoded_config,
        ),
    ):
        result = await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    client.get_account_info.assert_awaited_once_with(config_pda, commitment="finalized")
    client.get_multiple_accounts.assert_awaited_once_with(
        [config_pda, header_pda, cal_pda, usdc_pda],
        commitment="finalized",
    )
    assert result.header.status == "recovering"
    assert result.header.source_status == "live"
    assert result.header.account == str(header_pda)
    assert result.header.slot == 441
    assert result.cal.amount_base_units == cal_amount
    assert result.cal.token_account == str(cal_pda)
    assert result.cal.mint == str(cal_mint)
    assert result.cal.slot == 441
    assert result.usdc.amount_base_units == usdc_amount
    assert result.usdc.token_account == str(usdc_pda)
    assert result.usdc.mint == str(usdc_mint)
    assert result.program_config_account == str(config_pda)
    assert result.program_config_slot == 441


@pytest.mark.asyncio
async def test_balance_snapshot_rejects_wrong_program_config_owner() -> None:
    rider = Keypair().pubkey()
    config_account = _account(owner=TOKEN_PROGRAM_ID, data=b"config")
    bootstrap = SimpleNamespace(context=SimpleNamespace(slot=440), value=config_account)
    client = _rpc_client(bootstrap=bootstrap, snapshot=SimpleNamespace(value=[]))

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        pytest.raises(ValueError, match="ProgramConfig has program owner"),
    ):
        await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    client.get_multiple_accounts.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("program_version", [0x4C, 0x4D])
async def test_balance_snapshot_rejects_wrong_rider_balance_owner(program_version: int) -> None:
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    config_account = _account(owner=DEFAULT_BOULDER_PROGRAM_ID, data=b"config")
    bootstrap = SimpleNamespace(context=SimpleNamespace(slot=440), value=config_account)
    _, header_bump = _derive_rider_balance_pda(rider, DEFAULT_BOULDER_PROGRAM_ID)
    snapshot = SimpleNamespace(
        context=SimpleNamespace(slot=441),
        value=[
            config_account,
            _account(
                owner=TOKEN_PROGRAM_ID,
                data=_rider_balance_data(
                    rider=rider,
                    status=0,
                    bump=header_bump,
                ),
            ),
            None,
            None,
        ],
    )
    client = _rpc_client(bootstrap=bootstrap, snapshot=snapshot)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_program_config_account",
            return_value={
                "initialized": True,
                "program_version": program_version,
                "cal_mint": str(cal_mint),
                "usdc_mint": str(usdc_mint),
            },
        ),
        pytest.raises(ValueError, match="RiderBalance has program owner"),
    ):
        await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("program_version", [0x4C, 0x4D])
async def test_balance_snapshot_rejects_wrong_cal_mint(program_version: int) -> None:
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    wrong_cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    config_account = _account(owner=DEFAULT_BOULDER_PROGRAM_ID, data=b"config")
    bootstrap = SimpleNamespace(context=SimpleNamespace(slot=440), value=config_account)
    _, header_bump = _derive_rider_balance_pda(rider, DEFAULT_BOULDER_PROGRAM_ID)
    balance_authority, _ = _derive_rider_balance_auth_pda(
        rider,
        DEFAULT_BOULDER_PROGRAM_ID,
    )
    snapshot = SimpleNamespace(
        context=SimpleNamespace(slot=441),
        value=[
            config_account,
            _account(
                owner=DEFAULT_BOULDER_PROGRAM_ID,
                data=_rider_balance_data(
                    rider=rider,
                    status=0,
                    bump=header_bump,
                ),
            ),
            _account(
                owner=TOKEN_PROGRAM_ID,
                data=_token_account_data(
                    mint=wrong_cal_mint,
                    owner=balance_authority,
                    amount=42,
                ),
            ),
            None,
        ],
    )
    client = _rpc_client(bootstrap=bootstrap, snapshot=snapshot)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_program_config_account",
            return_value={
                "initialized": True,
                "program_version": program_version,
                "cal_mint": str(cal_mint),
                "usdc_mint": str(usdc_mint),
            },
        ),
        pytest.raises(ValueError, match="SPL token account mint"),
    ):
        await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("program_version", [0x4C, 0x4D])
async def test_missing_balance_accounts_are_known_missing_not_unavailable(program_version: int) -> None:
    rider = Keypair().pubkey()
    cal_mint = Keypair().pubkey()
    usdc_mint = Keypair().pubkey()
    config_account = _account(owner=DEFAULT_BOULDER_PROGRAM_ID, data=b"config")
    bootstrap = SimpleNamespace(context=SimpleNamespace(slot=700), value=config_account)
    snapshot = SimpleNamespace(
        context=SimpleNamespace(slot=701),
        value=[config_account, None, None, None],
    )
    client = _rpc_client(bootstrap=bootstrap, snapshot=snapshot)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        patch(
            "app.solana_direct._decode_anchor_program_config_account",
            return_value={
                "initialized": True,
                "program_version": program_version,
                "cal_mint": str(cal_mint),
                "usdc_mint": str(usdc_mint),
            },
        ),
    ):
        result = await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )

    assert not result.header.initialized
    assert result.header.status is None
    assert result.header.source_status == "not_initialized"
    assert result.header.slot == 701
    for asset in (result.cal, result.usdc):
        assert not asset.exists
        assert asset.amount_base_units == 0
        assert asset.status == "not_initialized"
        assert asset.slot == 701


@pytest.mark.asyncio
async def test_balance_snapshot_propagates_rpc_unavailability() -> None:
    rider = Keypair().pubkey()
    client = AsyncMock()
    client.get_account_info = AsyncMock(side_effect=RuntimeError("rpc down"))
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=False)

    with (
        patch("app.solana_direct.AsyncClient", return_value=client),
        pytest.raises(RuntimeError, match="rpc down"),
    ):
        await get_rider_balance_account_snapshot(
            str(rider),
            rpc_url="https://rpc.example",
            program_id=DEFAULT_BOULDER_PROGRAM_ID,
        )
