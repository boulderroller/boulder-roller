from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Optional

from ..config import get_environment, is_public_environment


BALANCE_ROLLOUT_ORDER = (
    "collect_dung",
    "deposit_cal",
    "withdraw_cal",
    "add_funds",
    "create_vault_usdc",
    "withdraw_to_wallet",
)

BALANCE_ROLLOUT_LABELS = {
    "collect_dung": "Collect DUNG",
    "deposit_cal": "Deposit CAL",
    "withdraw_cal": "Withdraw CAL",
    "add_funds": "Add funds",
    "create_vault_usdc": "Create Vault or Pay with USDC",
    "withdraw_to_wallet": "Withdraw to wallet",
}

BALANCE_ROLLOUT_BOUNDARY_ACTIONS = {"add_funds", "withdraw_to_wallet"}

BALANCE_ROLLOUT_STAGE_ACTIONS = {
    "off": (),
    "collect_dung": ("collect_dung",),
    "deposit_cal": ("collect_dung", "deposit_cal"),
    "withdraw_cal": ("collect_dung", "deposit_cal", "withdraw_cal"),
    "create_vault_usdc": (
        "collect_dung",
        "deposit_cal",
        "withdraw_cal",
        "add_funds",
        "create_vault_usdc",
    ),
    "all": BALANCE_ROLLOUT_ORDER,
}

BALANCE_ROUTE_ACTION_ALIASES = {
    "create_vault": "create_vault_usdc",
    "cal_usdc": "create_vault_usdc",
}


@dataclass(frozen=True)
class BalanceActionRollout:
    key: str
    label: str
    enabled: bool
    order: int
    boundary_action: bool = False


@dataclass(frozen=True)
class BalanceProductionRollout:
    stage: str
    cohort: str
    enabled_actions: tuple[str, ...]
    action_order: tuple[str, ...]
    actions: tuple[BalanceActionRollout, ...]
    owner: Optional[str]
    rollback_owner: Optional[str]
    rollback_contact: Optional[str]
    started_at: Optional[str]
    enforced: bool
    order_valid: bool
    blockers: tuple[str, ...]

    def as_dict(self) -> dict:
        return {
            "stage": self.stage,
            "cohort": self.cohort,
            "enabled_actions": list(self.enabled_actions),
            "action_order": list(self.action_order),
            "actions": [action.__dict__ for action in self.actions],
            "owner": self.owner,
            "rollback_owner": self.rollback_owner,
            "rollback_contact": self.rollback_contact,
            "started_at": self.started_at,
            "enforced": self.enforced,
            "order_valid": self.order_valid,
            "blockers": list(self.blockers),
        }


def _parse_bool(value: Optional[str], default: bool = False) -> bool:
    if value is None:
        return default
    normalized = value.strip().lower()
    if not normalized:
        return default
    return normalized in {"1", "true", "yes", "on"}


def _normalized_stage() -> str:
    stage = os.getenv("BALANCE_ROLLOUT_STAGE", "off").strip().lower()
    return stage if stage in BALANCE_ROLLOUT_STAGE_ACTIONS else "off"


def _normalized_action(action: str) -> str:
    normalized = action.strip().lower().replace("-", "_")
    return BALANCE_ROUTE_ACTION_ALIASES.get(normalized, normalized)


def _enabled_actions_for_stage(stage: str) -> set[str]:
    enabled = set(BALANCE_ROLLOUT_STAGE_ACTIONS[stage])
    for action in BALANCE_ROLLOUT_ORDER:
        env_key = f"BALANCE_ROLLOUT_ENABLE_{action.upper()}"
        if env_key not in os.environ:
            continue
        raw_value = os.getenv(env_key)
        if raw_value is None or not raw_value.strip():
            continue
        if _parse_bool(raw_value):
            enabled.add(action)
        else:
            enabled.discard(action)
    return enabled


def _order_valid(enabled: set[str]) -> bool:
    if not enabled:
        return True
    highest_index = max(BALANCE_ROLLOUT_ORDER.index(action) for action in enabled)
    expected_prefix = set(BALANCE_ROLLOUT_ORDER[: highest_index + 1])
    return enabled == expected_prefix


def _enforced(environment: str) -> bool:
    default = is_public_environment(environment)
    return _parse_bool(os.getenv("BALANCE_ROLLOUT_ENFORCED"), default=default)


def get_balance_production_rollout(environment: Optional[str] = None) -> BalanceProductionRollout:
    env = environment or get_environment()
    stage = _normalized_stage()
    enabled = _enabled_actions_for_stage(stage)
    enabled_ordered = tuple(action for action in BALANCE_ROLLOUT_ORDER if action in enabled)
    order_valid = _order_valid(enabled)
    owner = os.getenv("BALANCE_ROLLOUT_OWNER") or None
    rollback_owner = os.getenv("BALANCE_ROLLOUT_ROLLBACK_OWNER") or None
    rollback_contact = os.getenv("BALANCE_ROLLOUT_ROLLBACK_CONTACT") or None
    blockers: list[str] = []

    if not order_valid:
        blockers.append("balance_rollout_order_invalid")
    if enabled and not owner:
        blockers.append("balance_rollout_owner_missing")
    if enabled and not rollback_owner:
        blockers.append("balance_rollout_rollback_owner_missing")

    return BalanceProductionRollout(
        stage=stage,
        cohort=os.getenv("BALANCE_ROLLOUT_COHORT", "internal").strip().lower() or "internal",
        enabled_actions=enabled_ordered,
        action_order=BALANCE_ROLLOUT_ORDER,
        actions=tuple(
            BalanceActionRollout(
                key=action,
                label=BALANCE_ROLLOUT_LABELS[action],
                enabled=action in enabled,
                order=index + 1,
                boundary_action=action in BALANCE_ROLLOUT_BOUNDARY_ACTIONS,
            )
            for index, action in enumerate(BALANCE_ROLLOUT_ORDER)
        ),
        owner=owner,
        rollback_owner=rollback_owner,
        rollback_contact=rollback_contact,
        started_at=os.getenv("BALANCE_ROLLOUT_STARTED_AT") or None,
        enforced=_enforced(env),
        order_valid=order_valid,
        blockers=tuple(blockers),
    )


def is_balance_action_enabled(action: str, environment: Optional[str] = None) -> bool:
    rollout = get_balance_production_rollout(environment=environment)
    if not rollout.enforced:
        return True
    normalized = _normalized_action(action)
    return rollout.order_valid and not rollout.blockers and normalized in rollout.enabled_actions
