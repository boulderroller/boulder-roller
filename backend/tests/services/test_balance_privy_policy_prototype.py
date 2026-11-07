from __future__ import annotations

import dataclasses

import pytest

from app.services.balance_privy_policy_prototype import (
    DEFAULT_PRIVY_POLICY_CONSTRAINTS,
    BalancePrivyPolicyAttempt,
    BalancePrivyPolicyFailure,
    constraint_for_action,
    evaluate_privy_policy_attempt,
)


def _valid_attempt(action_type: str = "deposit_cal") -> BalancePrivyPolicyAttempt:
    constraint = constraint_for_action(action_type)
    return BalancePrivyPolicyAttempt(
        action_type=action_type,
        policy_id=constraint.policy_id,
        program_id=constraint.program_id,
        instruction_name=constraint.instruction_name,
        asset=constraint.asset,
        mint=constraint.mint,
        amount_base_units=max(1, constraint.max_amount_base_units // 2),
        source=constraint.required_accounts.get("source", "rider_source_account"),
        destination=constraint.destination,
        accounts=dict(constraint.required_accounts),
        expires_at_unix=1_900_000_000,
        now_unix=1_800_000_000,
    )


@pytest.mark.parametrize("action_type", DEFAULT_PRIVY_POLICY_CONSTRAINTS)
def test_valid_policy_fixture_allows_expected_balance_attempt(action_type: str) -> None:
    decision = evaluate_privy_policy_attempt(_valid_attempt(action_type))

    assert decision.allowed
    assert decision.failures == ()
    assert decision.provider_enforced_fields
    assert decision.fallback_behavior


def test_wrong_program_is_rejected() -> None:
    attempt = dataclasses.replace(_valid_attempt(), program_id="BadProgram11111111111111111111111111111111")

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.WRONG_PROGRAM in decision.failures


def test_wrong_custom_anchor_instruction_is_rejected_by_fixture() -> None:
    attempt = dataclasses.replace(_valid_attempt(), instruction_name="unstakeCalFromVault")

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.WRONG_INSTRUCTION in decision.failures


def test_wrong_account_role_is_rejected_by_fixture() -> None:
    attempt = _valid_attempt()
    accounts = dict(attempt.accounts)
    accounts["vault_cal_escrow"] = "attacker_cal_escrow"

    decision = evaluate_privy_policy_attempt(dataclasses.replace(attempt, accounts=accounts))

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.WRONG_ACCOUNT in decision.failures


def test_missing_account_role_is_rejected_by_fixture() -> None:
    attempt = _valid_attempt()
    accounts = dict(attempt.accounts)
    accounts.pop("vault_cal_escrow")

    decision = evaluate_privy_policy_attempt(dataclasses.replace(attempt, accounts=accounts))

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.MISSING_ACCOUNT in decision.failures


def test_wrong_mint_is_rejected() -> None:
    attempt = dataclasses.replace(_valid_attempt(), mint="FakeMint111111111111111111111111111111111111")

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.WRONG_MINT in decision.failures


def test_wrong_destination_is_rejected() -> None:
    attempt = dataclasses.replace(_valid_attempt(), destination="attacker_destination")

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.WRONG_DESTINATION in decision.failures


def test_over_limit_amount_is_rejected() -> None:
    constraint = constraint_for_action("deposit_cal")
    attempt = dataclasses.replace(_valid_attempt(), amount_base_units=constraint.max_amount_base_units + 1)

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.OVER_LIMIT_AMOUNT in decision.failures


def test_expired_operation_is_rejected() -> None:
    attempt = dataclasses.replace(_valid_attempt(), now_unix=1_900_000_000)

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.EXPIRED_OPERATION in decision.failures


def test_address_lookup_table_usage_is_rejected_for_address_bound_policy() -> None:
    attempt = dataclasses.replace(
        _valid_attempt(),
        address_lookup_table_addresses=("lookup-table-pubkey",),
    )

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert BalancePrivyPolicyFailure.ADDRESS_LOOKUP_TABLE in decision.failures


def test_boundary_action_is_not_policy_signable() -> None:
    attempt = dataclasses.replace(_valid_attempt(), action_type="withdraw_to_wallet")

    decision = evaluate_privy_policy_attempt(attempt)

    assert not decision.allowed
    assert decision.failures == (BalancePrivyPolicyFailure.UNSUPPORTED_ACTION,)
    assert decision.fallback_behavior == ("use wallet-boundary confirmation",)


@pytest.mark.parametrize("action_type", ("collect_dung", "deposit_cal", "withdraw_cal", "create_vault"))
def test_custom_anchor_policy_is_not_provider_sufficient_without_boulder_constraints(
    action_type: str,
) -> None:
    decision = evaluate_privy_policy_attempt(_valid_attempt(action_type))

    assert decision.allowed
    assert not decision.provider_sufficient_for_production
    assert "custom Anchor instruction name" in decision.provider_gap_fields
    assert "custom Anchor account role equality" in decision.provider_gap_fields
    assert "solana_program_instruction.programId" in decision.provider_enforced_fields


def test_token_transfer_policy_can_be_provider_sufficient_when_quote_matches() -> None:
    decision = evaluate_privy_policy_attempt(_valid_attempt("pay_usdc"))

    assert decision.allowed
    assert decision.provider_sufficient_for_production
    assert "solana_token_program_instruction.TransferChecked.mint" in decision.provider_enforced_fields
    assert decision.provider_gap_fields == ()
