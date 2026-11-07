import ast
from pathlib import Path


SCRIPT_PATH = Path(__file__).parents[1] / "scripts" / "smoke_full_stack.py"
REWARD_IDENTITY_FIELDS = {
    "signature_v2_hex",
    "start_lat",
    "start_lon",
    "end_lat",
    "end_lon",
}


def _keyword_names(call: ast.Call) -> set[str]:
    return {keyword.arg for keyword in call.keywords if keyword.arg is not None}


def _dict_string_keys(node: ast.AST) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def test_full_stack_smoke_carries_authoritative_reward_identity() -> None:
    tree = ast.parse(SCRIPT_PATH.read_text())

    smoke_climb = next(
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == "SmokeClimb"
    )
    smoke_fields = {
        statement.target.id
        for statement in smoke_climb.body
        if isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
    }
    assert REWARD_IDENTITY_FIELDS <= smoke_fields

    repository_create = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "create_vault"
    )
    assert REWARD_IDENTITY_FIELDS <= _keyword_names(repository_create)

    smoke_upsert = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "upsert_indexed_vault"
    )
    assert REWARD_IDENTITY_FIELDS <= _keyword_names(smoke_upsert)

    indexed_vault_updates = [
        _dict_string_keys(node.args[0])
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "update"
        and node.args
    ]
    assert any(REWARD_IDENTITY_FIELDS <= keys for keys in indexed_vault_updates)
