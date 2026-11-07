from pathlib import Path


ROOT = Path(__file__).resolve().parents[4]
REGISTRY = ROOT / "docs" / "design" / "PRODUCT_PATH_REGISTRY.md"


def test_product_path_registry_defines_core_paths_and_forcing_contracts():
    text = REGISTRY.read_text()

    for path_id in [f"P{idx}" for idx in range(1, 11)]:
        assert f"## {path_id} " in text

    for required_section in [
        "Contract",
        "State transition",
        "Surfaces",
        "Gates",
        "Tracker",
    ]:
        assert required_section in text

    assert "record ride -> upload evidence -> process evidence -> attest ride -> earn on climb -> settle vault -> view result -> public verify" in text
    assert "on-chain truth, attested truth, or projected truth" in text


def test_boulderscan_registry_preserves_explorer_language_boundary():
    text = REGISTRY.read_text()

    assert "BoulderScan is the public proof witness" in text
    assert "Etherscan/Solscan" in text
    assert "Transaction" in text
    assert "Account" in text
    assert "Vault" in text
    assert "Metadata" in text
    assert "The rider app can soften language" in text
