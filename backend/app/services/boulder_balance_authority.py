"""Boulder Roller Balance authority-model contract.

This module is intentionally declarative. The transaction coordinator imports
this catalog to decide which execution models are allowed for each rider action
before it builds or submits a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class AuthorityModel(str, Enum):
    """Execution authority classes used by Balance-aware backend code."""

    BACKEND_AUTHORIZED = "backend_authorized"
    PERMISSIONLESS_FOR_RIDER = "permissionless_for_rider"
    APP_BALANCE = "app_balance"
    RIDER_SESSION = "rider_session"
    PRIVY_POLICY_SIGNER = "privy_policy_signer"
    SPL_DELEGATE = "spl_delegate"
    WALLET_BOUNDARY = "wallet_boundary"


class BoundaryStepUp(str, Enum):
    """Step-up class required before a route may proceed."""

    NONE = "none"
    WALLET_CONFIRMATION = "wallet_confirmation"
    ACCOUNT_SECURITY = "account_security"
    RECOVERY_LOCK = "recovery_lock"


@dataclass(frozen=True)
class PrivyPolicyScope:
    """Minimum provider-side constraints for embedded-wallet app signers."""

    chain_type: str
    method: str
    attach_after_login_only: bool
    required_conditions: tuple[str, ...]
    deny_private_key_export: bool = True
    require_static_account_keys_for_address_rules: bool = True


@dataclass(frozen=True)
class SplDelegateScope:
    """Minimum SPL delegate constraints for external-wallet accounts."""

    approval_instruction: str
    transfer_authority: str
    one_delegate_per_token_account: bool
    owner_signs_approval: bool
    owner_signs_revoke: bool
    allowance_in_base_units: bool
    revocation_instruction: str


@dataclass(frozen=True)
class BalanceAuthorityPolicy:
    """Allowed authority models and invariants for one rider action."""

    action: str
    rider_label: str
    authority_models: tuple[AuthorityModel, ...]
    assets: tuple[str, ...]
    program_constraints: tuple[str, ...]
    account_constraints: tuple[str, ...]
    amount_constraints: tuple[str, ...]
    destination_constraints: tuple[str, ...]
    step_up: BoundaryStepUp = BoundaryStepUp.NONE
    requires_program_config: bool = True
    requires_revocation_check: bool = True
    privy_policy: PrivyPolicyScope | None = None
    spl_delegate: SplDelegateScope | None = None
    wallet_boundary_fallback: bool = False
    revocation_controls: tuple[str, ...] = ()
    provider_verification: tuple[str, ...] = ()
    fallback_behavior: tuple[str, ...] = ()

    @property
    def primary_models(self) -> tuple[AuthorityModel, ...]:
        """No-prompt or low-prompt models. Wallet boundary is fallback only."""

        return tuple(model for model in self.authority_models if model is not AuthorityModel.WALLET_BOUNDARY)


PRIVY_SOLANA_POLICY_BASE = PrivyPolicyScope(
    chain_type="solana",
    method="signAndSendTransaction",
    attach_after_login_only=True,
    required_conditions=(
        "solana_program_instruction.programId",
        "solana_token_program_instruction.instructionName",
        "solana_token_program_instruction.TransferChecked.mint",
        "solana_token_program_instruction.TransferChecked.amount",
        "system.current_unix_timestamp",
    ),
)


SPL_TOKEN_DELEGATE_BASE = SplDelegateScope(
    approval_instruction="ApproveChecked",
    transfer_authority="owner_or_delegate",
    one_delegate_per_token_account=True,
    owner_signs_approval=True,
    owner_signs_revoke=True,
    allowance_in_base_units=True,
    revocation_instruction="Revoke",
)


BALANCE_REVOCATION_CONTROLS = (
    "RiderBalance status is not locked, recovering, or revoked",
    "RiderBalance.revoked_at == 0",
    "backend coordinator refuses stale rider session, policy, or delegate id",
    "Balance-funded Vault actions require an unexpired on-chain rider session",
    "settings can revoke Privy policy signer and SPL delegate authority",
)


PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION = (
    "prototype exact Privy Solana policy constraints for Boulder Rollers Anchor instructions",
    "do not rely on address-based rules when transactions use address lookup tables",
    "store policy id and policy hash before coordinator execution",
)


SPL_DELEGATE_FALLBACK = (
    "use app-balance successor when assets are already inside Boulder Roller Balance",
    "use wallet-boundary fallback when policy/delegate capability is unavailable or revoked",
)


POLICIES: dict[str, BalanceAuthorityPolicy] = {
    "collect_dung": BalanceAuthorityPolicy(
        action="collect_dung",
        rider_label="Collect DUNG",
        authority_models=(
            AuthorityModel.PERMISSIONLESS_FOR_RIDER,
            AuthorityModel.APP_BALANCE,
            AuthorityModel.PRIVY_POLICY_SIGNER,
        ),
        assets=("DUNG",),
        program_constraints=(
            "Boulder Rollers program id",
            "ProgramConfig DUNG mint",
            "ProgramConfig DUNG treasury",
            "DungMintState supply cap",
        ),
        account_constraints=(
            "VaultStake PDA derives from rider and vault",
            "current collect_stake_rewards_for destination is the rider DUNG ATA",
            "a RiderBalance DUNG destination requires a distinct successor instruction",
        ),
        amount_constraints=("unclaimed rewards less configured harvest fee",),
        destination_constraints=(
            "net DUNG to exact rider wallet ATA",
            "fee DUNG to ProgramConfig treasury",
        ),
        privy_policy=PRIVY_SOLANA_POLICY_BASE,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        provider_verification=PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION,
        fallback_behavior=("use permissionless-for-rider successor without policy signer",),
    ),
    "deposit_cal": BalanceAuthorityPolicy(
        action="deposit_cal",
        rider_label="Deposit CAL",
        authority_models=(
            AuthorityModel.RIDER_SESSION,
            AuthorityModel.PRIVY_POLICY_SIGNER,
            AuthorityModel.SPL_DELEGATE,
            AuthorityModel.WALLET_BOUNDARY,
        ),
        assets=("CAL", "LP"),
        program_constraints=("Boulder Rollers program id", "ProgramConfig CAL mint"),
        account_constraints=(
            "source CAL account owned by RiderBalance, policy wallet, or approved delegate source",
            "Balance-funded path has the exact active rider-session signer",
            "VaultStake PDA derives from rider and vault",
            "Balance-funded LP destination is the canonical sealed rider-and-Vault position account",
        ),
        amount_constraints=("amount is caller-requested and coordinator-capped",),
        destination_constraints=("CAL destination is exact Vault CAL Escrow PDA",),
        privy_policy=PRIVY_SOLANA_POLICY_BASE,
        spl_delegate=SPL_TOKEN_DELEGATE_BASE,
        wallet_boundary_fallback=True,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        provider_verification=PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION,
        fallback_behavior=SPL_DELEGATE_FALLBACK,
    ),
    "withdraw_cal": BalanceAuthorityPolicy(
        action="withdraw_cal",
        rider_label="Withdraw CAL",
        authority_models=(
            AuthorityModel.RIDER_SESSION,
            AuthorityModel.PRIVY_POLICY_SIGNER,
            AuthorityModel.SPL_DELEGATE,
            AuthorityModel.WALLET_BOUNDARY,
        ),
        assets=("CAL", "LP"),
        program_constraints=("Boulder Rollers program id", "ProgramConfig CAL mint"),
        account_constraints=(
            "Balance-funded LP source is the canonical sealed rider-and-Vault position account",
            "other execution paths use the canonical position or an explicitly approved delegated source",
            "Balance-funded path has the exact active rider-session signer",
            "VaultStake PDA derives from rider and vault",
        ),
        amount_constraints=("LP burn amount is caller-requested and coordinator-capped",),
        destination_constraints=("CAL return destination is RiderBalance CAL token PDA",),
        privy_policy=PRIVY_SOLANA_POLICY_BASE,
        spl_delegate=SPL_TOKEN_DELEGATE_BASE,
        wallet_boundary_fallback=True,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        provider_verification=PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION,
        fallback_behavior=SPL_DELEGATE_FALLBACK,
    ),
    "create_vault": BalanceAuthorityPolicy(
        action="create_vault",
        rider_label="Create Vault",
        authority_models=(
            AuthorityModel.RIDER_SESSION,
            AuthorityModel.PRIVY_POLICY_SIGNER,
            AuthorityModel.SPL_DELEGATE,
            AuthorityModel.WALLET_BOUNDARY,
        ),
        assets=("CAL", "USDC", "DUNG"),
        program_constraints=(
            "Boulder Rollers program id",
            "ProgramConfig CAL mint",
            "ProgramConfig USDC mint",
            "ProgramConfig USDC treasury",
            "ProgramConfig vault creation amounts",
        ),
        account_constraints=(
            "climb signature is 64 bytes",
            "Balance-funded path has the exact active rider-session signer",
            "VaultCounter, Vault, LocalLegend, and VaultActivation PDAs are canonical",
            "created Vault.minter equals rider",
        ),
        amount_constraints=(
            "CAL burn/debit equals configured amount",
            "USDC transfer equals configured amount",
        ),
        destination_constraints=("USDC destination is ProgramConfig treasury token account",),
        privy_policy=PRIVY_SOLANA_POLICY_BASE,
        spl_delegate=SPL_TOKEN_DELEGATE_BASE,
        wallet_boundary_fallback=True,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        provider_verification=PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION,
        fallback_behavior=SPL_DELEGATE_FALLBACK,
    ),
    "pay_usdc": BalanceAuthorityPolicy(
        action="pay_usdc",
        rider_label="Pay with USDC",
        authority_models=(
            AuthorityModel.RIDER_SESSION,
            AuthorityModel.PRIVY_POLICY_SIGNER,
            AuthorityModel.SPL_DELEGATE,
            AuthorityModel.WALLET_BOUNDARY,
        ),
        assets=("USDC",),
        program_constraints=("Boulder Rollers program id", "ProgramConfig USDC mint"),
        account_constraints=("USDC source is RiderBalance, policy wallet, or approved delegate source",),
        amount_constraints=("amount equals ProgramConfig amount or coordinator quote",),
        destination_constraints=("USDC destination is ProgramConfig treasury token account",),
        privy_policy=PRIVY_SOLANA_POLICY_BASE,
        spl_delegate=SPL_TOKEN_DELEGATE_BASE,
        wallet_boundary_fallback=True,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        provider_verification=PRIVY_SOLANA_CUSTOM_INSTRUCTION_VERIFICATION,
        fallback_behavior=SPL_DELEGATE_FALLBACK,
    ),
    "add_funds": BalanceAuthorityPolicy(
        action="add_funds",
        rider_label="Add funds",
        authority_models=(AuthorityModel.WALLET_BOUNDARY,),
        assets=("CAL", "USDC", "SOL"),
        program_constraints=("funding provider or wallet transfer boundary",),
        account_constraints=("destination is rider wallet or RiderBalance token PDA selected by the rider",),
        amount_constraints=("amount is rider-confirmed",),
        destination_constraints=("destination is shown before confirmation",),
        step_up=BoundaryStepUp.WALLET_CONFIRMATION,
        fallback_behavior=("show provider/onramp or wallet confirmation inline",),
        requires_program_config=False,
        requires_revocation_check=False,
    ),
    "withdraw_to_wallet": BalanceAuthorityPolicy(
        action="withdraw_to_wallet",
        rider_label="Withdraw to wallet",
        authority_models=(AuthorityModel.WALLET_BOUNDARY,),
        assets=("CAL", "USDC", "DUNG"),
        program_constraints=("Boulder Rollers program id",),
        account_constraints=("source is RiderBalance token PDA",),
        amount_constraints=("amount is rider-confirmed",),
        destination_constraints=("destination wallet token account is rider-confirmed",),
        step_up=BoundaryStepUp.WALLET_CONFIRMATION,
        revocation_controls=BALANCE_REVOCATION_CONTROLS,
        fallback_behavior=("stop and show account security state when Balance authority is revoked",),
    ),
    "transfer_out": BalanceAuthorityPolicy(
        action="transfer_out",
        rider_label="Transfer out",
        authority_models=(AuthorityModel.WALLET_BOUNDARY,),
        assets=("CAL", "USDC", "DUNG"),
        program_constraints=("wallet provider boundary",),
        account_constraints=("source wallet belongs to rider",),
        amount_constraints=("amount is rider-confirmed",),
        destination_constraints=("recipient is rider-confirmed",),
        step_up=BoundaryStepUp.WALLET_CONFIRMATION,
        requires_program_config=False,
        revocation_controls=(
            "account security state is active",
            "backend coordinator refuses transfer while account is locked or recovering",
        ),
        fallback_behavior=("show provider wallet confirmation inline",),
    ),
    "export_wallet": BalanceAuthorityPolicy(
        action="export_wallet",
        rider_label="Export wallet",
        authority_models=(AuthorityModel.WALLET_BOUNDARY,),
        assets=("wallet_key_material",),
        program_constraints=("Privy wallet security boundary",),
        account_constraints=("rider is authenticated with provider step-up",),
        amount_constraints=("not applicable",),
        destination_constraints=("not applicable",),
        step_up=BoundaryStepUp.ACCOUNT_SECURITY,
        requires_program_config=False,
        requires_revocation_check=False,
        fallback_behavior=("send rider through provider account-security flow",),
    ),
    "change_authority": BalanceAuthorityPolicy(
        action="change_authority",
        rider_label="Change authority",
        authority_models=(AuthorityModel.WALLET_BOUNDARY,),
        assets=("policy_signer", "delegate_authority", "account_recovery"),
        program_constraints=("Privy policy/signer and SPL delegate boundary",),
        account_constraints=("old policy/delegate is revoked before replacement is active",),
        amount_constraints=("not applicable",),
        destination_constraints=("not applicable",),
        step_up=BoundaryStepUp.ACCOUNT_SECURITY,
        requires_program_config=False,
        requires_revocation_check=True,
        revocation_controls=(
            "old Privy policy signer is removed or rotated before replacement",
            "old SPL delegate allowance is revoked before replacement",
            "backend coordinator refuses stale policy_or_delegate_id",
        ),
        fallback_behavior=("lock Balance execution until replacement authority is confirmed",),
    ),
}


NORMAL_BALANCE_ACTIONS = (
    "collect_dung",
    "deposit_cal",
    "withdraw_cal",
    "create_vault",
    "pay_usdc",
)

BOUNDARY_ACTIONS = (
    "add_funds",
    "withdraw_to_wallet",
    "transfer_out",
    "export_wallet",
    "change_authority",
)


def policy_for_action(action: str) -> BalanceAuthorityPolicy:
    if action in STAGE1_WALLET_ACTIONS:
        return BalanceAuthorityPolicy(
            action=action, rider_label="TIM: " + action,
            authority_models=(AuthorityModel.WALLET_BOUNDARY,), assets=("SOL", "SPL"),
            program_constraints=("Release-pinned 0x4D ABI and enabled Stage 1 actions",),
            account_constraints=("Exact signed-in owner and canonical Stage 1 accounts",),
            amount_constraints=("Exact requested base units or durable unpaid owner proof",),
            destination_constraints=("Own wallet recipient and canonical custody",),
            step_up=BoundaryStepUp.WALLET_CONFIRMATION,
        )
    try:
        return POLICIES[action]
    except KeyError as exc:
        raise ValueError(f"Unknown Balance authority action: {action}") from exc


STAGE1_WALLET_ACTIONS = frozenset("stage1_" + name for name in (
    "registration", "self_claim", "claim_transport", "pledge", "withdrawal_notice", "cancel_notice",
    "begin_withdrawal", "complete_withdrawal", "convert_pledge",
))


def all_policies() -> tuple[BalanceAuthorityPolicy, ...]:
    return tuple(POLICIES[action] for action in sorted(POLICIES))


def validate_policy_catalog() -> list[str]:
    """Return catalog problems; an empty list means the contract is coherent."""

    problems: list[str] = []
    for action, policy in POLICIES.items():
        if not policy.authority_models:
            problems.append(f"{action}: missing authority model")
        if action in NORMAL_BALANCE_ACTIONS and policy.step_up is not BoundaryStepUp.NONE:
            problems.append(f"{action}: normal balance action should not require boundary step-up")
        if action in BOUNDARY_ACTIONS and policy.step_up is BoundaryStepUp.NONE:
            problems.append(f"{action}: boundary action must require step-up")
        if AuthorityModel.PRIVY_POLICY_SIGNER in policy.authority_models and policy.privy_policy is None:
            problems.append(f"{action}: Privy signer allowed without policy scope")
        if AuthorityModel.SPL_DELEGATE in policy.authority_models and policy.spl_delegate is None:
            problems.append(f"{action}: SPL delegate allowed without delegate scope")
        if policy.privy_policy and not policy.privy_policy.attach_after_login_only:
            problems.append(f"{action}: Privy signer must attach only after login/account setup")
        if policy.spl_delegate and not policy.spl_delegate.owner_signs_revoke:
            problems.append(f"{action}: SPL delegate path must define owner revocation")
        if policy.wallet_boundary_fallback and AuthorityModel.WALLET_BOUNDARY not in policy.authority_models:
            problems.append(f"{action}: wallet fallback enabled without wallet-boundary authority")
        if policy.requires_revocation_check and not policy.revocation_controls:
            problems.append(f"{action}: revocation check required without revocation controls")
        if AuthorityModel.PRIVY_POLICY_SIGNER in policy.authority_models and not policy.provider_verification:
            problems.append(f"{action}: Privy signer path must name provider verification")
        if policy.wallet_boundary_fallback and not policy.fallback_behavior:
            problems.append(f"{action}: wallet fallback must name concrete fallback behavior")
    return problems
