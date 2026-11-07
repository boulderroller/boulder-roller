import ast
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "backend" / "scripts" / "seed_vaults_onchain.py"


def test_operational_seed_script_cannot_emit_generation_one_activation():
    source = SCRIPT.read_text(encoding="utf-8")
    module = ast.parse(source)
    function = next(
        node
        for node in module.body
        if isinstance(node, ast.AsyncFunctionDef)
        and node.name == "seed_and_activate_vault"
    )
    first_statement = function.body[1]

    assert isinstance(first_statement, ast.Raise)
    assert "legacy generation-1 vault seeding is disabled" in ast.unparse(
        first_statement
    )
