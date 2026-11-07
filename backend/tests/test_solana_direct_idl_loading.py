from pathlib import Path

from app import solana_direct


def test_accounts_coder_loads_idl_from_packaged_backend_layout(
    tmp_path: Path,
    monkeypatch,
):
    packaged_root = tmp_path / "app"
    packaged_module = packaged_root / "app" / "solana_direct.py"
    packaged_module.parent.mkdir(parents=True)
    packaged_module.touch()

    source_idl = (
        Path(__file__).resolve().parents[1] / "idl" / "boulder_rollers.json"
    )
    packaged_idl = packaged_root / "idl" / "boulder_rollers.json"
    packaged_idl.parent.mkdir()
    packaged_idl.write_bytes(source_idl.read_bytes())

    monkeypatch.setattr(solana_direct, "__file__", str(packaged_module))
    solana_direct._get_boulder_accounts_coder.cache_clear()
    try:
        assert solana_direct._get_boulder_accounts_coder() is not None
    finally:
        solana_direct._get_boulder_accounts_coder.cache_clear()
