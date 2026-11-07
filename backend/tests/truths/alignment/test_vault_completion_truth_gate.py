"""Vault completion truth regression gates.

These are static, fast gates for the protocol lane's replay -> activation ->
live completion boundary. They intentionally avoid importing the app graph; the
goal is to catch drift before a devnet smoke burns transactions.
"""

from __future__ import annotations

import json

from ._alignment_helpers import anchor_program_source, read_file, repo_root


IDL_SURFACES = (
    "protocol/anchor/idl/boulder_rollers.json",
    "backend/idl/boulder_rollers.json",
    "web/portal/public/idl/boulder_rollers.json",
)


def _load_idl(relative_path: str) -> dict:
    return json.loads((repo_root() / relative_path).read_text(encoding="utf-8"))


def _account_type(idl: dict, name: str) -> dict:
    for account_type in idl.get("accounts", []) + idl.get("types", []):
        if account_type["name"] == name:
            return account_type
    raise AssertionError(f"{name} missing from IDL")


def _event(idl: dict, name: str) -> dict:
    for event in idl["events"]:
        if event["name"] == name:
            return event
    raise AssertionError(f"{name} missing from IDL")


def _instruction(idl: dict, name: str) -> dict:
    for instruction in idl["instructions"]:
        if instruction["name"] == name:
            return instruction
    raise AssertionError(f"{name} missing from IDL")


def test_public_idl_surfaces_share_completion_evidence_shape() -> None:
    """All runtime IDL copies expose the same completion evidence contract."""
    idls = {path: _load_idl(path) for path in IDL_SURFACES}
    canonical = idls["protocol/anchor/idl/boulder_rollers.json"]

    for path, idl in idls.items():
        assert idl == canonical, f"{path} diverged from protocol Anchor IDL"

        names = [instruction["name"] for instruction in idl["instructions"]]
        assert "recordClimbCompletion" not in names, "V1 completion was removed"
        assert "ClimbCompletionReceipt" not in [account["name"] for account in idl["accounts"]]

        record_climb_v2 = _instruction(idl, "recordClimbCompletionV2")
        assert [arg["name"] for arg in record_climb_v2["args"]] == [
            "completionTimeS",
            "calTribute",
            "completionEvidenceHash",
        ]
        receipt_v2_fields = _account_type(idl, "ClimbCompletionReceiptV2")[
            "type"
        ]["fields"]
        assert [field["name"] for field in receipt_v2_fields] == [
            "rideAttestation",
            "vault",
            "evidenceVersion",
            "calTributed",
            "completionEvidenceHash",
            "bump",
        ]

        for event_name in ("ClimbCompleted", "VaultCompleted"):
            event_fields = _event(idl, event_name)["fields"]
            assert "completionEvidenceHash" in [field["name"] for field in event_fields]


def test_typescript_client_exposes_completion_evidence_contract() -> None:
    """Generated TS client must move with the committed IDL."""
    ts_client = read_file("protocol/anchor/clients/typescript/boulder_rollers.ts")
    required_tokens = (
        '"name": "recordClimbCompletionV2"',
        '"name": "completionEvidenceHash"',
        '"name": "climbCompletionReceipt"',
        '"name": "climbCompletionReceiptV2"',
        '"name": "ClimbCompleted"',
        '"name": "VaultCompleted"',
    )
    missing = [token for token in required_tokens if token not in ts_client]
    assert not missing, "Generated Anchor TS client missing tokens: " + ", ".join(missing)


def test_activation_keeps_v1_while_live_and_smoke_use_tribute_bound_v2() -> None:
    """Activation replay stays V1; new economic writes share the V2 identity."""
    surfaces = {
        "backend/app/services/vault_activation_service.py": read_file(
            "backend/app/services/vault_activation_service.py"
        ),
        "backend/app/services/ride_economic_plan_builder.py": read_file(
            "backend/app/services/ride_economic_plan_builder.py"
        ),
        "backend/scripts/smoke_devnet_economics.py": read_file(
            "backend/scripts/smoke_devnet_economics.py"
        ),
    }

    assert "build_vault_completion_evidence_hash" in surfaces[
        "backend/app/services/vault_activation_service.py"
    ]
    assert "build_completion_evidence_v2" in surfaces[
        "backend/app/services/ride_economic_plan_builder.py"
    ]
    assert "build_climb_completion_evidence_v2" in surfaces[
        "backend/scripts/smoke_devnet_economics.py"
    ]

    for path, text in surfaces.items():
        assert 'f"{user_profile.wallet}:{best_vault.id}' not in text, (
            f"{path} still has the retired colon-delimited evidence format"
        )
        assert "BR_VAULT_COMPLETION_V1" not in text, (
            f"{path} must import, not redefine, its evidence domain"
        )


def test_live_completion_side_effects_are_activation_gated() -> None:
    """Live DB/economic side effects must stay behind active seed lifecycle."""
    builder = read_file("backend/app/services/ride_economic_plan_builder.py")
    coordinator = read_file("backend/app/services/ride_economic_coordinator.py")
    anchor = anchor_program_source()

    gate_idx = builder.index("not is_vault_live_for_completion(indexed_vault)")
    evidence_idx = builder.index(
        "processor.ride_executor.build_completion_evidence_v2("
    )
    assert gate_idx < evidence_idx
    assert "continue" in builder[gate_idx:evidence_idx]

    onchain_idx = coordinator.index(
        "execution = await self.executor.record_climb_completion_receipt("
    )
    confirmation_idx = coordinator.index(
        "confirmed = await self.repository.confirm_completion_step("
    )
    projection_idx = coordinator.index(
        "await self.repository.reconcile_completion_projection("
    )
    assert onchain_idx < confirmation_idx < projection_idx
    assert "completion_evidence_hash=bytes.fromhex(" in coordinator[
        onchain_idx:confirmation_idx
    ]

    v2_context = anchor[anchor.index("pub struct RecordClimbCompletionV2"):]
    assert "constraint = vault_activation.is_active @ ErrorCode::VaultNotActive" in (
        v2_context
    )
    assert "constraint = vault_activation.permits_new_economic_history()" in (
        v2_context
    )
