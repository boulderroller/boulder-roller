import base64
import json

import pytest
from solders.keypair import Keypair

from app import solana_direct


def _clear_key_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "FEE_PAYER_KEYPAIR",
        "BACKEND_AUTHORITY_KEYPAIR",
        "EXPECTED_BACKEND_AUTHORITY",
        "SOLANA_PAYER_SECRET",
        "SOLANA_PAYER_PATH",
        "SOLANA_BACKEND_AUTHORITY_SECRET",
        "SOLANA_BACKEND_AUTHORITY_PATH",
    ):
        monkeypatch.delenv(name, raising=False)


def test_load_keypair_accepts_base64_raw_bytes():
    keypair = Keypair()
    encoded = base64.b64encode(bytes(keypair)).decode("ascii")

    loaded = solana_direct._load_keypair(encoded)

    assert loaded.pubkey() == keypair.pubkey()


def test_load_keypair_accepts_base64_json_array():
    keypair = Keypair()
    encoded = base64.b64encode(json.dumps(list(bytes(keypair))).encode("utf-8")).decode("ascii")

    loaded = solana_direct._load_keypair(encoded)

    assert loaded.pubkey() == keypair.pubkey()


def test_load_fee_payer_keypair_prefers_modern_env(monkeypatch: pytest.MonkeyPatch):
    _clear_key_env(monkeypatch)
    modern = Keypair()
    legacy = Keypair()

    monkeypatch.setenv("FEE_PAYER_KEYPAIR", base64.b64encode(bytes(modern)).decode("ascii"))
    monkeypatch.setenv("SOLANA_PAYER_SECRET", json.dumps(list(bytes(legacy))))

    loaded = solana_direct.load_fee_payer_keypair()

    assert loaded.pubkey() == modern.pubkey()


def test_load_backend_authority_uses_role_specific_default(monkeypatch: pytest.MonkeyPatch):
    _clear_key_env(monkeypatch)
    backend_authority = Keypair()
    loaded_paths: list[str] = []

    def fake_load_keypair(secret: str) -> Keypair:
        loaded_paths.append(secret)
        return backend_authority

    monkeypatch.setattr(solana_direct, "_load_keypair", fake_load_keypair)

    loaded = solana_direct.load_backend_authority_keypair()

    assert loaded.pubkey() == backend_authority.pubkey()
    assert loaded_paths == ["~/.config/solana/boulderroller-backend-authority.json"]


def test_load_backend_authority_respects_expected_pubkey(monkeypatch: pytest.MonkeyPatch):
    _clear_key_env(monkeypatch)
    backend_authority = Keypair()
    wrong_expected = str(Keypair().pubkey())

    monkeypatch.setenv(
        "BACKEND_AUTHORITY_KEYPAIR",
        base64.b64encode(bytes(backend_authority)).decode("ascii"),
    )
    monkeypatch.setenv("EXPECTED_BACKEND_AUTHORITY", wrong_expected)

    with pytest.raises(ValueError, match="EXPECTED_BACKEND_AUTHORITY"):
        solana_direct.load_backend_authority_keypair()
