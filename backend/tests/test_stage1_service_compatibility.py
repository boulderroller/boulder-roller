import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from solders.pubkey import Pubkey

from app import program_compatibility, solana_direct
from app.program_compatibility import ProgramCompatibility


@pytest.fixture(autouse=True)
def observation_store(monkeypatch):
    """Unit store retains observations when the process-local cache is reset."""
    from app import db_pool

    rows = {}
    async def fetchval(_sql, genesis, program, version):
        key = (genesis, program)
        rows[key] = max(rows.get(key, version), version)
        return rows[key]

    connection = AsyncMock()
    connection.fetchval.side_effect = fetchval
    pool = SimpleNamespace(acquire=lambda: connection)
    connection.__aenter__.return_value = connection
    monkeypatch.setattr(db_pool, "get_pool", AsyncMock(return_value=pool))
    monkeypatch.setattr(program_compatibility, "_networks", {})
    return rows


def program_config_bytes(version: int) -> bytes:
    # Both released ProgramConfig layouts are exactly 334 bytes. Use serialized
    # bytes, not a mocked decoded object, so this proves the runtime IDL decoder.
    data = bytearray(334)
    data[:8] = hashlib.sha256(b"account:ProgramConfig").digest()[:8]
    data[72] = version
    data[73] = 1
    data[75:107] = bytes([3]) * 32
    data[107:139] = bytes([7]) * 32
    data[325:333] = (1704110400).to_bytes(8, "little", signed=True)
    data[333] = 2
    return bytes(data)


@pytest.mark.parametrize("version", [0x4C, 0x4D, 0x4E])
def test_real_program_config_bytes_decode_every_version_without_stage1_fields(version):
    decoded = solana_direct._decode_anchor_program_config_account(program_config_bytes(version), Pubkey.default())
    assert decoded["program_version"] == version
    assert decoded["cal_mint"] == str(Pubkey.from_bytes(bytes([3]) * 32))
    assert decoded["dung_mint"] == str(Pubkey.from_bytes(bytes([7]) * 32))
    assert decoded["settlement_clock_v2_starts_at"] == 1704110400
    assert decoded["settlement_clock_version"] == 2
    assert not any("stage1" in field for field in decoded)


def test_cutover_state_never_falls_back_after_version_advance():
    state = ProgramCompatibility()
    for version in [0x4C, 0x4C]:
        state.observe(version)
        with pytest.raises(RuntimeError, match="not available on this network"):
            state.require_stage1()
    state.observe(0x4D)
    state.require_stage1()
    with pytest.raises(ValueError, match="version downgrade"):
        state.observe(0x4C)
    assert state.program_version == 0x4D
    assert not state.stage1_available
    with pytest.raises(ValueError, match="version downgrade"):
        state.require_stage1()


def test_stage1_stays_available_across_the_0x4E_advance():
    state = ProgramCompatibility()
    state.observe(0x4D)
    state.require_stage1()
    state.observe(0x4E)
    state.require_stage1()
    assert state.program_version == 0x4E
    with pytest.raises(ValueError, match="version downgrade"):
        state.observe(0x4D)
    assert not state.stage1_available


@pytest.mark.asyncio
async def test_0x4E_config_read_keeps_stage1_without_new_service_or_config(monkeypatch):
    monkeypatch.setattr(program_compatibility, "_networks", {})
    versions = iter([0x4D, 0x4E, 0x4D])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_genesis_hash.return_value = SimpleNamespace(value="localnet-0x4e-genesis")
    client.get_account_info.side_effect = lambda *a, **kw: SimpleNamespace(
        value=SimpleNamespace(data=program_config_bytes(next(versions)), owner=Pubkey.default())
    )
    monkeypatch.setattr(solana_direct, "AsyncClient", lambda *a, **kw: client)
    config = solana_direct.ReadOnlyConfig("http://127.0.0.1:18899", Pubkey.default())
    assert (await solana_direct.get_stage1_program_config_account(config))["program_version"] == 0x4D
    assert (await solana_direct.get_stage1_program_config_account(config))["program_version"] == 0x4E
    with pytest.raises(ValueError, match="version downgrade"):
        await solana_direct.get_program_config_account(config)


@pytest.mark.asyncio
async def test_next_config_read_enables_stage1_without_new_service_or_config(monkeypatch):
    monkeypatch.setattr(program_compatibility, "_networks", {})
    versions = iter([0x4C, 0x4D, 0x4C])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_genesis_hash.return_value = SimpleNamespace(value="localnet-cutover-genesis")
    client.get_account_info.side_effect = lambda *a, **kw: SimpleNamespace(
        value=SimpleNamespace(data=program_config_bytes(next(versions)), owner=Pubkey.default())
    )
    monkeypatch.setattr(solana_direct, "AsyncClient", lambda *a, **kw: client)
    config = solana_direct.ReadOnlyConfig("http://127.0.0.1:18899", Pubkey.default())
    with pytest.raises(RuntimeError, match="not available on this network"):
        await solana_direct.get_stage1_program_config_account(config)
    assert (await solana_direct.get_stage1_program_config_account(config))["program_version"] == 0x4D
    # Reconstructing config cannot clear the service's observed high-water mark.
    with pytest.raises(ValueError, match="version downgrade"):
        await solana_direct.get_program_config_account(solana_direct.ReadOnlyConfig(config.rpc_url, config.program_id))


@pytest.mark.asyncio
async def test_backend_only_advance_survives_process_restart(monkeypatch, observation_store):
    versions = iter([0x4D, 0x4C])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_genesis_hash.return_value = SimpleNamespace(value="restart-genesis")
    client.get_account_info.side_effect = lambda *a, **kw: SimpleNamespace(
        value=SimpleNamespace(data=program_config_bytes(next(versions)), owner=Pubkey.default())
    )
    monkeypatch.setattr(solana_direct, "AsyncClient", lambda *a, **kw: client)
    config = solana_direct.ReadOnlyConfig("http://127.0.0.1:18899", Pubkey.default())
    assert (await solana_direct.get_stage1_program_config_account(config))["program_version"] == 0x4D
    program_compatibility._networks.clear()  # A new process has no in-memory evidence.
    with pytest.raises(ValueError, match="version downgrade"):
        await solana_direct.get_program_config_account(config)


@pytest.mark.asyncio
async def test_missing_config_disables_previously_enabled_stage1(monkeypatch):
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_genesis_hash.return_value = SimpleNamespace(value="missing-genesis")
    client.get_account_info.side_effect = [
        SimpleNamespace(value=SimpleNamespace(data=program_config_bytes(0x4D), owner=Pubkey.default())),
        SimpleNamespace(value=None),
    ]
    monkeypatch.setattr(solana_direct, "AsyncClient", lambda *a, **kw: client)
    config = solana_direct.ReadOnlyConfig("http://127.0.0.1:18899", Pubkey.default())
    await solana_direct.get_stage1_program_config_account(config)
    assert await solana_direct.get_program_config_account(config) is None
    state = program_compatibility._networks[(config.rpc_url, str(config.program_id))]
    assert not state.stage1_available
    with pytest.raises(RuntimeError, match="ProgramConfig is missing"):
        state.require_stage1()


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected", [0xFF, 0x4B, 0x4F])
@pytest.mark.parametrize("initial", [None, 0x4C, 0x4D])
async def test_rejected_version_never_reaches_store_and_current_still_advances(monkeypatch, observation_store, rejected, initial):
    from app import db_pool

    versions = iter(([initial] if initial is not None else []) + [rejected, 0x4D])
    client = AsyncMock()
    client.__aenter__.return_value = client
    client.get_genesis_hash.return_value = SimpleNamespace(value="rejected-version-genesis")
    client.get_account_info.side_effect = lambda *a, **kw: SimpleNamespace(
        value=SimpleNamespace(data=program_config_bytes(next(versions)), owner=Pubkey.default())
    )
    monkeypatch.setattr(solana_direct, "AsyncClient", lambda *a, **kw: client)
    config = solana_direct.ReadOnlyConfig("http://127.0.0.1:18899", Pubkey.default())
    if initial is not None:
        assert (await solana_direct.get_program_config_account(config))["program_version"] == initial
    before = observation_store.copy()
    calls_before = db_pool.get_pool.await_count
    with pytest.raises(ValueError, match="version mismatch"):
        await solana_direct.get_program_config_account(config)
    assert db_pool.get_pool.await_count == calls_before, "reject before accessing the persistence boundary"
    assert observation_store == before
    state = program_compatibility.program_compatibility(config.rpc_url, str(config.program_id))
    assert state.program_version == initial
    assert not state.stage1_available
    assert (await solana_direct.get_stage1_program_config_account(config))["program_version"] == 0x4D
    assert observation_store[("rejected-version-genesis", str(config.program_id))] == 0x4D
    assert state.stage1_available


def test_cutover_has_no_appended_fields_on_existing_legacy_accounts():
    root = Path(__file__).resolve().parents[2]
    old = json.loads((root / "protocol/anchor/abi/v0x4c.json").read_text())
    current = json.loads((root / "protocol/anchor/abi/v0x4d.json").read_text())
    current_accounts = {account["name"]: account for account in current["accounts"]}
    for account in old["accounts"]:
        assert current_accounts[account["name"]] == account, (
            "An appended legacy field needs an explicit absent-on-0x4C decoder; never zero-pad it"
        )


def test_0x4E_decodes_every_0x4D_account_it_keeps_unchanged():
    root = Path(__file__).resolve().parents[2]
    old = {a["name"]: a for a in json.loads((root / "protocol/anchor/abi/v0x4d.json").read_text())["accounts"]}
    current = json.loads((root / "protocol/anchor/abi/v0x4e.json").read_text())["accounts"]
    assert set(old) - {a["name"] for a in current} == {"ClimbCompletionReceipt"}
    for account in current:
        assert old[account["name"]] == account


@pytest.mark.asyncio
@pytest.mark.parametrize("version,stage1", [(0x4C, "not available on this network"), (0x4D, "available"), (0x4E, "available")])
async def test_chain_health_reports_observed_capability(monkeypatch, version, stage1):
    monkeypatch.setenv("ACCESS_TOKEN_SECRET", "stage1-compatibility-test-access-secret")
    monkeypatch.setenv("REFRESH_TOKEN_SECRET", "stage1-compatibility-test-refresh-secret")
    from app.routes.health import chain_health

    monkeypatch.setattr(solana_direct, "get_program_config_account", AsyncMock(return_value={"program_version": version}))
    assert await chain_health() == {"status": "ok", "program_version": version, "stage1": stage1}
