import pytest

from app.services.boulder_balance_authority import (
    BOUNDARY_ACTIONS,
    NORMAL_BALANCE_ACTIONS,
    AuthorityModel,
    BoundaryStepUp,
    policy_for_action,
    validate_policy_catalog,
)


def test_balance_authority_catalog_is_coherent() -> None:
    assert validate_policy_catalog() == []


@pytest.mark.parametrize("action", NORMAL_BALANCE_ACTIONS)
def test_normal_balance_actions_do_not_require_boundary_step_up(action: str) -> None:
    policy = policy_for_action(action)

    assert policy.step_up is BoundaryStepUp.NONE
    assert AuthorityModel.BACKEND_AUTHORIZED not in policy.authority_models
    assert AuthorityModel.WALLET_BOUNDARY not in policy.primary_models
    assert policy.requires_program_config
    assert "RiderBalance.revoked_at == 0" in policy.revocation_controls


@pytest.mark.parametrize("action", BOUNDARY_ACTIONS)
def test_boundary_actions_are_explicit_wallet_or_security_events(action: str) -> None:
    policy = policy_for_action(action)

    assert policy.authority_models == (AuthorityModel.WALLET_BOUNDARY,)
    assert policy.step_up is not BoundaryStepUp.NONE
    assert policy.privy_policy is None
    assert policy.spl_delegate is None


@pytest.mark.parametrize(
    "action",
    ("collect_dung", "deposit_cal", "withdraw_cal", "create_vault", "pay_usdc"),
)
def test_privy_policy_signer_constraints_are_not_generic_wallet_signing(action: str) -> None:
    policy = policy_for_action(action)

    assert AuthorityModel.PRIVY_POLICY_SIGNER in policy.authority_models
    assert policy.privy_policy is not None
    assert policy.privy_policy.chain_type == "solana"
    assert policy.privy_policy.method == "signAndSendTransaction"
    assert policy.privy_policy.attach_after_login_only
    assert policy.privy_policy.deny_private_key_export
    assert "solana_program_instruction.programId" in policy.privy_policy.required_conditions
    assert "solana_token_program_instruction.instructionName" in policy.privy_policy.required_conditions
    assert "solana_token_program_instruction.TransferChecked.mint" in policy.privy_policy.required_conditions
    assert "solana_token_program_instruction.TransferChecked.amount" in policy.privy_policy.required_conditions
    assert "system.current_unix_timestamp" in policy.privy_policy.required_conditions
    assert any("Boulder Rollers Anchor instructions" in item for item in policy.provider_verification)


@pytest.mark.parametrize("action", ("deposit_cal", "withdraw_cal", "create_vault", "pay_usdc"))
def test_spl_delegate_paths_are_limited_and_revocable(action: str) -> None:
    policy = policy_for_action(action)

    assert AuthorityModel.SPL_DELEGATE in policy.authority_models
    assert policy.spl_delegate is not None
    assert policy.spl_delegate.approval_instruction == "ApproveChecked"
    assert policy.spl_delegate.transfer_authority == "owner_or_delegate"
    assert policy.spl_delegate.one_delegate_per_token_account
    assert policy.spl_delegate.owner_signs_approval
    assert policy.spl_delegate.owner_signs_revoke
    assert policy.spl_delegate.allowance_in_base_units
    assert policy.spl_delegate.revocation_instruction == "Revoke"
    assert policy.wallet_boundary_fallback
    assert policy.fallback_behavior


def test_usdc_paths_are_bound_to_program_config_treasury_and_amount() -> None:
    create_vault = policy_for_action("create_vault")
    pay_usdc = policy_for_action("pay_usdc")

    assert "USDC" in create_vault.assets
    assert "ProgramConfig USDC mint" in create_vault.program_constraints
    assert "ProgramConfig USDC treasury" in create_vault.program_constraints
    assert "USDC transfer equals configured amount" in create_vault.amount_constraints
    assert "USDC destination is ProgramConfig treasury token account" in create_vault.destination_constraints

    assert pay_usdc.assets == ("USDC",)
    assert "ProgramConfig USDC mint" in pay_usdc.program_constraints
    assert "amount equals ProgramConfig amount or coordinator quote" in pay_usdc.amount_constraints
    assert "USDC destination is ProgramConfig treasury token account" in pay_usdc.destination_constraints


def test_withdraw_cal_is_not_withdraw_to_wallet() -> None:
    withdraw_cal = policy_for_action("withdraw_cal")
    withdraw_to_wallet = policy_for_action("withdraw_to_wallet")

    assert withdraw_cal.rider_label == "Withdraw CAL"
    assert withdraw_cal.step_up is BoundaryStepUp.NONE
    assert "CAL return destination is RiderBalance CAL token PDA" in withdraw_cal.destination_constraints

    assert withdraw_to_wallet.rider_label == "Withdraw to wallet"
    assert withdraw_to_wallet.step_up is BoundaryStepUp.WALLET_CONFIRMATION
    assert withdraw_to_wallet.authority_models == (AuthorityModel.WALLET_BOUNDARY,)


def test_unknown_balance_authority_action_raises() -> None:
    with pytest.raises(ValueError, match="Unknown Balance authority action"):
        policy_for_action("sign_everything_with_the_rider_wallet")
