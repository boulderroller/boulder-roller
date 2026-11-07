"""Executable Privy policy fixture for Boulder Roller Balance.

This module does not call Privy. It models the policy shape Boulder Roller
expects before a route is allowed to ask an embedded-wallet policy signer to
execute a Balance action.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Mapping

from .boulder_balance_authority import AuthorityModel, policy_for_action


DEVNET_BOULDER_ROLLERS_PROGRAM_ID = "EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH"
SPL_TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
DEVNET_CAL_MINT = "4bxTCxEQp993cXs5nqhfWthRCPSTDv5K6PMgsfunEaJh"
DEVNET_DUNG_MINT = "CqDFJWLpr49tB8xjHegy5JR5jwMCfmhicjuWawtKLeCk"
DEVNET_USDC_MINT = "Gh9ZwEmdLJ8DscKNTkTqPbNwLNNBjuSzaG9Vp2KGtKJr"


class BalancePrivyPolicyFailure(str, Enum):
    """Reasons a prepared operation is not safe for policy-signer execution."""

    UNSUPPORTED_ACTION = "unsupported_action"
    WRONG_PROGRAM = "wrong_program"
    WRONG_INSTRUCTION = "wrong_instruction"
    WRONG_MINT = "wrong_mint"
    WRONG_DESTINATION = "wrong_destination"
    WRONG_ACCOUNT = "wrong_account"
    MISSING_ACCOUNT = "missing_account"
    OVER_LIMIT_AMOUNT = "over_limit_amount"
    EXPIRED_OPERATION = "expired_operation"
    ADDRESS_LOOKUP_TABLE = "address_lookup_table"


@dataclass(frozen=True)
class BalancePrivyPolicyConstraint:
    """Expected policy scope for one Balance action."""

    action_type: str
    policy_id: str
    program_id: str
    instruction_name: str
    asset: str
    mint: str
    destination: str
    max_amount_base_units: int
    required_accounts: Mapping[str, str]
    provider_enforced_fields: tuple[str, ...]
    provider_gap_fields: tuple[str, ...]
    fallback_behavior: tuple[str, ...]

    @property
    def provider_sufficient_for_production(self) -> bool:
        """Whether provider policy alone can express this complete contract."""

        return not self.provider_gap_fields


@dataclass(frozen=True)
class BalancePrivyPolicyAttempt:
    """Prepared operation fields checked before provider policy execution."""

    action_type: str
    policy_id: str
    program_id: str
    instruction_name: str
    asset: str
    mint: str
    amount_base_units: int
    source: str
    destination: str
    accounts: Mapping[str, str]
    expires_at_unix: int
    now_unix: int
    address_lookup_table_addresses: tuple[str, ...] = ()


@dataclass(frozen=True)
class BalancePrivyPolicyDecision:
    """Policy prototype result for CI, route adapters, and support logs."""

    allowed: bool
    failures: tuple[BalancePrivyPolicyFailure, ...]
    provider_sufficient_for_production: bool
    provider_enforced_fields: tuple[str, ...]
    provider_gap_fields: tuple[str, ...]
    fallback_behavior: tuple[str, ...]


CUSTOM_ANCHOR_PROVIDER_FIELDS = (
    "solana_program_instruction.programId",
    "system.current_unix_timestamp",
)


CUSTOM_ANCHOR_PROVIDER_GAPS = (
    "custom Anchor instruction name",
    "custom Anchor account role equality",
    "custom Anchor amount argument",
    "custom Anchor destination account",
)


TOKEN_TRANSFER_PROVIDER_FIELDS = (
    "solana_token_program_instruction.instructionName",
    "solana_token_program_instruction.TransferChecked.mint",
    "solana_token_program_instruction.TransferChecked.amount",
    "recipient token account",
    "system.current_unix_timestamp",
)


DEFAULT_PRIVY_POLICY_CONSTRAINTS: dict[str, BalancePrivyPolicyConstraint] = {
    "collect_dung": BalancePrivyPolicyConstraint(
        action_type="collect_dung",
        policy_id="br-balance-collect-dung-devnet",
        program_id=DEVNET_BOULDER_ROLLERS_PROGRAM_ID,
        instruction_name="collectStakeRewardsFor",
        asset="DUNG",
        mint=DEVNET_DUNG_MINT,
        destination="rider_dung_ata",
        max_amount_base_units=50_000_000_000,
        required_accounts={
            "vault": "vault_pda",
            "vault_stake": "vault_stake_pda",
            "dung_mint": DEVNET_DUNG_MINT,
            "staker_dung_account": "rider_dung_ata",
            "protocol_treasury": "program_config_dung_treasury",
            "program_config": "program_config_pda",
        },
        provider_enforced_fields=CUSTOM_ANCHOR_PROVIDER_FIELDS,
        provider_gap_fields=CUSTOM_ANCHOR_PROVIDER_GAPS,
        fallback_behavior=(
            "prefer permissionless-for-rider successor",
            "fall back to app-balance execution",
        ),
    ),
    "deposit_cal": BalancePrivyPolicyConstraint(
        action_type="deposit_cal",
        policy_id="br-balance-deposit-cal-devnet",
        program_id=DEVNET_BOULDER_ROLLERS_PROGRAM_ID,
        instruction_name="stakeCalInVault",
        asset="CAL",
        mint=DEVNET_CAL_MINT,
        destination="vault_cal_escrow_pda",
        max_amount_base_units=1_000_000_000_000,
        required_accounts={
            "vault": "vault_pda",
            "vault_stake": "vault_stake_pda",
            "staker_cal_ata": "rider_cal_ata",
            "vault_cal_escrow": "vault_cal_escrow_pda",
            "vault_lp_mint": "vault_lp_mint_pda",
            "staker_lp_account": "rider_lp_ata",
        },
        provider_enforced_fields=CUSTOM_ANCHOR_PROVIDER_FIELDS,
        provider_gap_fields=CUSTOM_ANCHOR_PROVIDER_GAPS,
        fallback_behavior=(
            "use RiderBalance app-balance deposit path when funds are inside Boulder Roller",
            "fall back to wallet-boundary confirmation when policy signer cannot prove the exact instruction",
        ),
    ),
    "withdraw_cal": BalancePrivyPolicyConstraint(
        action_type="withdraw_cal",
        policy_id="br-balance-withdraw-cal-devnet",
        program_id=DEVNET_BOULDER_ROLLERS_PROGRAM_ID,
        instruction_name="unstakeCalFromVault",
        asset="LP",
        mint=DEVNET_CAL_MINT,
        destination="rider_cal_ata",
        max_amount_base_units=1_000_000_000_000,
        required_accounts={
            "vault": "vault_pda",
            "vault_stake": "vault_stake_pda",
            "staker_cal_ata": "rider_cal_ata",
            "vault_cal_escrow": "vault_cal_escrow_pda",
            "cal_mint": DEVNET_CAL_MINT,
            "vault_lp_mint": "vault_lp_mint_pda",
            "staker_lp_account": "rider_lp_ata",
        },
        provider_enforced_fields=CUSTOM_ANCHOR_PROVIDER_FIELDS,
        provider_gap_fields=CUSTOM_ANCHOR_PROVIDER_GAPS,
        fallback_behavior=(
            "use RiderBalance app-balance withdraw path when funds are inside Boulder Roller",
            "fall back to wallet-boundary confirmation when policy signer cannot prove the exact instruction",
        ),
    ),
    "create_vault": BalancePrivyPolicyConstraint(
        action_type="create_vault",
        policy_id="br-balance-create-vault-devnet",
        program_id=DEVNET_BOULDER_ROLLERS_PROGRAM_ID,
        instruction_name="createVaultWithUsdc",
        asset="CAL+USDC",
        mint=DEVNET_USDC_MINT,
        destination="program_config_usdc_treasury",
        max_amount_base_units=10_000_000,
        required_accounts={
            "vault_counter": "vault_counter_pda",
            "vault": "vault_pda",
            "local_legend": "local_legend_pda",
            "vault_activation": "vault_activation_pda",
            "creator_cal_account": "rider_cal_ata",
            "creator_usdc_account": "rider_usdc_ata",
            "protocol_usdc_account": "program_config_usdc_treasury",
            "usdc_mint": DEVNET_USDC_MINT,
            "program_config": "program_config_pda",
        },
        provider_enforced_fields=CUSTOM_ANCHOR_PROVIDER_FIELDS,
        provider_gap_fields=CUSTOM_ANCHOR_PROVIDER_GAPS,
        fallback_behavior=(
            "use createVaultFromBalanceCalUsdc app-balance successor",
            "fall back to wallet-boundary confirmation for external wallet funding",
        ),
    ),
    "pay_usdc": BalancePrivyPolicyConstraint(
        action_type="pay_usdc",
        policy_id="br-balance-pay-usdc-devnet",
        program_id=SPL_TOKEN_PROGRAM_ID,
        instruction_name="TransferChecked",
        asset="USDC",
        mint=DEVNET_USDC_MINT,
        destination="program_config_usdc_treasury",
        max_amount_base_units=10_000_000,
        required_accounts={
            "source": "rider_usdc_ata",
            "mint": DEVNET_USDC_MINT,
            "destination": "program_config_usdc_treasury",
            "authority": "rider_embedded_wallet",
        },
        provider_enforced_fields=TOKEN_TRANSFER_PROVIDER_FIELDS,
        provider_gap_fields=(),
        fallback_behavior=(
            "use app-balance USDC debit when funds are inside Boulder Roller",
            "fall back to wallet-boundary confirmation for external wallet funding",
        ),
    ),
}


def constraint_for_action(action_type: str) -> BalancePrivyPolicyConstraint:
    """Return the executable fixture constraint for a policy-signable action."""

    policy = policy_for_action(action_type)
    if AuthorityModel.PRIVY_POLICY_SIGNER not in policy.authority_models:
        raise ValueError(f"{action_type}: Privy policy signer is not allowed")
    try:
        return DEFAULT_PRIVY_POLICY_CONSTRAINTS[action_type]
    except KeyError as exc:
        raise ValueError(f"{action_type}: missing Privy policy fixture") from exc


def evaluate_privy_policy_attempt(
    attempt: BalancePrivyPolicyAttempt,
    constraint: BalancePrivyPolicyConstraint | None = None,
) -> BalancePrivyPolicyDecision:
    """Evaluate a prepared operation against Boulder Roller's policy fixture."""

    try:
        expected = constraint or constraint_for_action(attempt.action_type)
    except ValueError:
        return BalancePrivyPolicyDecision(
            allowed=False,
            failures=(BalancePrivyPolicyFailure.UNSUPPORTED_ACTION,),
            provider_sufficient_for_production=False,
            provider_enforced_fields=(),
            provider_gap_fields=(),
            fallback_behavior=("use wallet-boundary confirmation",),
        )

    failures: list[BalancePrivyPolicyFailure] = []
    if attempt.policy_id != expected.policy_id:
        failures.append(BalancePrivyPolicyFailure.UNSUPPORTED_ACTION)
    if attempt.program_id != expected.program_id:
        failures.append(BalancePrivyPolicyFailure.WRONG_PROGRAM)
    if attempt.instruction_name != expected.instruction_name:
        failures.append(BalancePrivyPolicyFailure.WRONG_INSTRUCTION)
    if attempt.asset != expected.asset:
        failures.append(BalancePrivyPolicyFailure.WRONG_MINT)
    if attempt.mint != expected.mint:
        failures.append(BalancePrivyPolicyFailure.WRONG_MINT)
    if attempt.destination != expected.destination:
        failures.append(BalancePrivyPolicyFailure.WRONG_DESTINATION)
    if attempt.amount_base_units <= 0 or attempt.amount_base_units > expected.max_amount_base_units:
        failures.append(BalancePrivyPolicyFailure.OVER_LIMIT_AMOUNT)
    if attempt.now_unix >= attempt.expires_at_unix:
        failures.append(BalancePrivyPolicyFailure.EXPIRED_OPERATION)
    if attempt.address_lookup_table_addresses:
        failures.append(BalancePrivyPolicyFailure.ADDRESS_LOOKUP_TABLE)

    for role, expected_account in expected.required_accounts.items():
        actual = attempt.accounts.get(role)
        if actual is None:
            failures.append(BalancePrivyPolicyFailure.MISSING_ACCOUNT)
        elif actual != expected_account:
            failures.append(BalancePrivyPolicyFailure.WRONG_ACCOUNT)

    return BalancePrivyPolicyDecision(
        allowed=not failures,
        failures=tuple(dict.fromkeys(failures)),
        provider_sufficient_for_production=expected.provider_sufficient_for_production,
        provider_enforced_fields=expected.provider_enforced_fields,
        provider_gap_fields=expected.provider_gap_fields,
        fallback_behavior=expected.fallback_behavior,
    )
