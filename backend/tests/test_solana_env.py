import importlib

from app import solana_env


def test_registry_defaults_match_anchor_addresses():
    registry = solana_env.load_devnet_address_registry()
    assert registry["programs"]["boulder_rollers"] == solana_env.DEFAULT_BOULDER_ROLLERS_PROGRAM_ID
    assert registry["mints"]["cal_mint"]["address"] == solana_env.DEFAULT_CAL_MINT_ADDRESS
    assert registry["mints"]["dung_mint"]["address"] == solana_env.DEFAULT_DUNG_MINT_ADDRESS


def test_env_override_program_id(monkeypatch):
    monkeypatch.setenv("BOULDER_ROLLERS_PROGRAM_ID", "override-program-id")
    assert solana_env.boulder_rollers_program_id() == "override-program-id"


def test_registry_loader_is_cacheable_after_reload():
    reloaded = importlib.reload(solana_env)
    registry = reloaded.load_devnet_address_registry()
    assert registry["cluster"] == "devnet"
