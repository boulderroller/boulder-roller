from __future__ import annotations

import pytest

from app.services.balance_rollout_readiness import (
    EXPOSED_SECRET_ROTATION_BEAD,
    MANAGED_SECRET_WORKFLOW_BEAD,
    BalanceRolloutBlockerCode,
    BalanceRolloutControl,
    BalanceRolloutReadinessError,
    BalanceRolloutReadinessEvidence,
    assert_balance_rollout_ready,
    evaluate_balance_rollout_readiness,
)


def _control_artifacts() -> dict[BalanceRolloutControl, str]:
    return {
        BalanceRolloutControl.REPLAY_IDEMPOTENCY: (
            "backend/tests/services/test_balance_transaction_coordinator.py::"
            "test_operation_id_is_stable_for_same_intent"
        ),
        BalanceRolloutControl.DESTINATION_SPOOFING: (
            "backend/tests/services/test_balance_privy_policy_prototype.py::"
            "test_wrong_destination_is_rejected"
        ),
        BalanceRolloutControl.TREASURY_SPOOFING: (
            "backend/tests/services/test_balance_privy_policy_prototype.py::"
            "test_wrong_account_role_is_rejected_by_fixture"
        ),
        BalanceRolloutControl.STALE_POLICY_DELEGATE: (
            "backend/tests/services/test_balance_transaction_coordinator.py::"
            "test_stale_policy_or_delegate_id_is_rejected_before_submission"
        ),
        BalanceRolloutControl.REVOCATION: (
            "backend/tests/services/test_balance_lifecycle.py::"
            "test_locked_recovering_and_revoked_disable_no_prompt_execution"
        ),
        BalanceRolloutControl.RATE_LIMIT: (
            "backend/tests/services/test_balance_transaction_coordinator.py::"
            "test_per_rider_daily_budget_blocks_action_before_insert"
        ),
        BalanceRolloutControl.SUPPORT_ADMIN_LEAKAGE: (
            "backend/tests/services/test_balance_operation_status.py::"
            "test_rider_status_omits_support_only_operation_fields"
        ),
    }


def _ready_evidence(**overrides: object) -> BalanceRolloutReadinessEvidence:
    values = {
        "fee_payer_pubkey": "BoulderRollerFeePayer111111111111111",
        "fee_payer_balance_lamports": 10_000_000_000,
        "fee_payer_alert_exercised": True,
        "signer_secret_owner": "platform-security",
        "provider_secret_owner": "platform-security",
        "managed_secret_workflow_ready": True,
        "managed_secret_dependency_bead": None,
        "open_secret_rotation_blocker_beads": (),
        "exercised_controls": _control_artifacts(),
    }
    values.update(overrides)
    return BalanceRolloutReadinessEvidence(**values)


def test_ready_evidence_allows_production_rollout() -> None:
    readiness = evaluate_balance_rollout_readiness(_ready_evidence())

    assert readiness.production_ready
    assert readiness.blockers == ()
    assert readiness.missing_controls == ()
    assert readiness.linked_blocker_beads == ()
    assert readiness.exercised_controls[BalanceRolloutControl.RATE_LIMIT.value].startswith("backend/tests/")


def test_fee_payer_funding_and_alert_exercise_are_required() -> None:
    readiness = evaluate_balance_rollout_readiness(
        _ready_evidence(
            fee_payer_balance_lamports=1_000_000_000,
            fee_payer_alert_exercised=False,
        )
    )

    codes = {blocker.code for blocker in readiness.blockers}
    assert not readiness.production_ready
    assert BalanceRolloutBlockerCode.FEE_PAYER_UNDERFUNDED in codes
    assert BalanceRolloutBlockerCode.FEE_PAYER_ALERT_NOT_EXERCISED in codes


def test_default_secret_blockers_link_existing_canonical_beads() -> None:
    readiness = evaluate_balance_rollout_readiness(
        _ready_evidence(
            managed_secret_workflow_ready=False,
            managed_secret_dependency_bead=MANAGED_SECRET_WORKFLOW_BEAD,
            open_secret_rotation_blocker_beads=(EXPOSED_SECRET_ROTATION_BEAD,),
        )
    )

    assert not readiness.production_ready
    assert readiness.linked_blocker_beads == (
        MANAGED_SECRET_WORKFLOW_BEAD,
        EXPOSED_SECRET_ROTATION_BEAD,
    )
    assert {
        BalanceRolloutBlockerCode.MANAGED_SECRET_WORKFLOW_BLOCKED,
        BalanceRolloutBlockerCode.EXPOSED_SECRET_ROTATION_OPEN,
    }.issubset({blocker.code for blocker in readiness.blockers})


def test_untracked_managed_secret_gap_blocks_rollout_separately() -> None:
    readiness = evaluate_balance_rollout_readiness(
        _ready_evidence(
            managed_secret_workflow_ready=False,
            managed_secret_dependency_bead=None,
        )
    )

    assert not readiness.production_ready
    assert BalanceRolloutBlockerCode.MANAGED_SECRET_WORKFLOW_UNTRACKED in {
        blocker.code for blocker in readiness.blockers
    }
    assert MANAGED_SECRET_WORKFLOW_BEAD not in readiness.linked_blocker_beads


def test_missing_security_control_evidence_blocks_with_named_control() -> None:
    artifacts = _control_artifacts()
    artifacts.pop(BalanceRolloutControl.RATE_LIMIT)
    readiness = evaluate_balance_rollout_readiness(_ready_evidence(exercised_controls=artifacts))

    assert not readiness.production_ready
    assert readiness.missing_controls == (BalanceRolloutControl.RATE_LIMIT,)
    assert BalanceRolloutBlockerCode.SECURITY_CONTROL_MISSING in {
        blocker.code for blocker in readiness.blockers
    }


def test_assert_balance_rollout_ready_raises_first_blocker() -> None:
    with pytest.raises(BalanceRolloutReadinessError, match="fee_payer_missing"):
        assert_balance_rollout_ready(_ready_evidence(fee_payer_pubkey=None))
