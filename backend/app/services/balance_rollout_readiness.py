"""Production readiness gate for Boulder Roller Balance rollout."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Mapping


EXPOSED_SECRET_ROTATION_BEAD = "boulderroller-v2-2f9w"
MANAGED_SECRET_WORKFLOW_BEAD = "boulderroller-v2-ttkx"

DEFAULT_FEE_PAYER_MINIMUM_LAMPORTS = 2_000_000_000
DEFAULT_FEE_PAYER_ALERT_THRESHOLD_LAMPORTS = 5_000_000_000


class BalanceRolloutControl(str, Enum):
    """Required evidence categories before production Balance rollout."""

    REPLAY_IDEMPOTENCY = "replay_idempotency"
    DESTINATION_SPOOFING = "destination_spoofing"
    TREASURY_SPOOFING = "treasury_spoofing"
    STALE_POLICY_DELEGATE = "stale_policy_delegate"
    REVOCATION = "revocation"
    RATE_LIMIT = "rate_limit"
    SUPPORT_ADMIN_LEAKAGE = "support_admin_leakage"


REQUIRED_BALANCE_ROLLOUT_CONTROLS = (
    BalanceRolloutControl.REPLAY_IDEMPOTENCY,
    BalanceRolloutControl.DESTINATION_SPOOFING,
    BalanceRolloutControl.TREASURY_SPOOFING,
    BalanceRolloutControl.STALE_POLICY_DELEGATE,
    BalanceRolloutControl.REVOCATION,
    BalanceRolloutControl.RATE_LIMIT,
    BalanceRolloutControl.SUPPORT_ADMIN_LEAKAGE,
)


class BalanceRolloutBlockerCode(str, Enum):
    """Stop conditions for production Balance rollout."""

    FEE_PAYER_MISSING = "fee_payer_missing"
    FEE_PAYER_BALANCE_UNKNOWN = "fee_payer_balance_unknown"
    FEE_PAYER_UNDERFUNDED = "fee_payer_underfunded"
    FEE_PAYER_ALERT_INVALID = "fee_payer_alert_invalid"
    FEE_PAYER_ALERT_NOT_EXERCISED = "fee_payer_alert_not_exercised"
    SECRET_OWNER_MISSING = "secret_owner_missing"
    MANAGED_SECRET_WORKFLOW_BLOCKED = "managed_secret_workflow_blocked"
    MANAGED_SECRET_WORKFLOW_UNTRACKED = "managed_secret_workflow_untracked"
    EXPOSED_SECRET_ROTATION_OPEN = "exposed_secret_rotation_open"
    SECURITY_CONTROL_MISSING = "security_control_missing"


@dataclass(frozen=True)
class BalanceRolloutBlocker:
    """One concrete reason production rollout must remain closed."""

    code: BalanceRolloutBlockerCode
    detail: str
    bead: str | None = None


@dataclass(frozen=True)
class BalanceRolloutReadinessEvidence:
    """Observed operational evidence for one Balance rollout decision."""

    fee_payer_pubkey: str | None = None
    fee_payer_balance_lamports: int | None = None
    fee_payer_minimum_lamports: int = DEFAULT_FEE_PAYER_MINIMUM_LAMPORTS
    fee_payer_alert_threshold_lamports: int = DEFAULT_FEE_PAYER_ALERT_THRESHOLD_LAMPORTS
    fee_payer_alert_exercised: bool = False
    signer_secret_owner: str | None = None
    provider_secret_owner: str | None = None
    managed_secret_workflow_ready: bool = False
    managed_secret_dependency_bead: str | None = MANAGED_SECRET_WORKFLOW_BEAD
    open_secret_rotation_blocker_beads: tuple[str, ...] = (EXPOSED_SECRET_ROTATION_BEAD,)
    exercised_controls: Mapping[BalanceRolloutControl | str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class BalanceRolloutReadiness:
    """Computed production stop/go state for Boulder Roller Balance."""

    production_ready: bool
    blockers: tuple[BalanceRolloutBlocker, ...]
    missing_controls: tuple[BalanceRolloutControl, ...]
    exercised_controls: Mapping[str, str]
    linked_blocker_beads: tuple[str, ...]


class BalanceRolloutReadinessError(RuntimeError):
    """Raised when a caller attempts production rollout with open blockers."""


def evaluate_balance_rollout_readiness(
    evidence: BalanceRolloutReadinessEvidence,
) -> BalanceRolloutReadiness:
    """Evaluate the release gate for production Balance execution.

    The result is intentionally conservative: fee-payer operations, signer
    custody, open secret blockers, and abuse-path controls must all be green
    before production rollout can proceed.
    """

    blockers: list[BalanceRolloutBlocker] = []
    linked_blockers: list[str] = []

    if not evidence.fee_payer_pubkey:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.FEE_PAYER_MISSING,
                detail="Balance fee payer pubkey is not recorded for the rollout.",
            )
        )
    if evidence.fee_payer_balance_lamports is None:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.FEE_PAYER_BALANCE_UNKNOWN,
                detail="Balance fee payer balance has not been checked.",
            )
        )
    elif evidence.fee_payer_balance_lamports < evidence.fee_payer_minimum_lamports:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.FEE_PAYER_UNDERFUNDED,
                detail=(
                    "Balance fee payer balance is below the minimum hot-wallet "
                    "runway for sponsored actions."
                ),
            )
        )
    if evidence.fee_payer_alert_threshold_lamports < evidence.fee_payer_minimum_lamports:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.FEE_PAYER_ALERT_INVALID,
                detail="Balance fee-payer alert threshold is below the minimum runway.",
            )
        )
    if not evidence.fee_payer_alert_exercised:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.FEE_PAYER_ALERT_NOT_EXERCISED,
                detail="Balance fee-payer low-balance alert has not been exercised.",
            )
        )

    missing_secret_owners = []
    if not evidence.signer_secret_owner:
        missing_secret_owners.append("signer")
    if not evidence.provider_secret_owner:
        missing_secret_owners.append("provider")
    if missing_secret_owners:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.SECRET_OWNER_MISSING,
                detail=f"Missing Balance secret owner(s): {', '.join(missing_secret_owners)}.",
            )
        )

    if not evidence.managed_secret_workflow_ready:
        dependency = evidence.managed_secret_dependency_bead
        if dependency:
            linked_blockers.append(dependency)
            blockers.append(
                BalanceRolloutBlocker(
                    code=BalanceRolloutBlockerCode.MANAGED_SECRET_WORKFLOW_BLOCKED,
                    detail="Balance signer/provider secrets still depend on managed secret cutover.",
                    bead=dependency,
                )
            )
        else:
            blockers.append(
                BalanceRolloutBlocker(
                    code=BalanceRolloutBlockerCode.MANAGED_SECRET_WORKFLOW_UNTRACKED,
                    detail="Managed secret workflow is not ready and no dependency bead is linked.",
                )
            )

    for bead in evidence.open_secret_rotation_blocker_beads:
        if not bead:
            continue
        linked_blockers.append(bead)
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.EXPOSED_SECRET_ROTATION_OPEN,
                detail="Required exposed-secret rotation blocker remains open.",
                bead=bead,
            )
        )

    exercised_controls = _normalize_controls(evidence.exercised_controls)
    missing_controls = tuple(
        control for control in REQUIRED_BALANCE_ROLLOUT_CONTROLS if not exercised_controls.get(control.value)
    )
    for control in missing_controls:
        blockers.append(
            BalanceRolloutBlocker(
                code=BalanceRolloutBlockerCode.SECURITY_CONTROL_MISSING,
                detail=f"Missing Balance security control evidence: {control.value}.",
            )
        )

    return BalanceRolloutReadiness(
        production_ready=not blockers,
        blockers=tuple(blockers),
        missing_controls=missing_controls,
        exercised_controls=exercised_controls,
        linked_blocker_beads=tuple(dict.fromkeys(linked_blockers)),
    )


def assert_balance_rollout_ready(evidence: BalanceRolloutReadinessEvidence) -> BalanceRolloutReadiness:
    """Return readiness or raise with the first blocker code."""

    readiness = evaluate_balance_rollout_readiness(evidence)
    if not readiness.production_ready:
        first = readiness.blockers[0]
        raise BalanceRolloutReadinessError(f"{first.code.value}: {first.detail}")
    return readiness


def _normalize_controls(
    controls: Mapping[BalanceRolloutControl | str, str],
) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for control, artifact in controls.items():
        key = control.value if isinstance(control, BalanceRolloutControl) else str(control)
        value = str(artifact).strip()
        if value:
            normalized[key] = value
    return normalized
