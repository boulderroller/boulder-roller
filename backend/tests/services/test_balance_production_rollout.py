from __future__ import annotations

from app.services.balance_production_rollout import (
    BALANCE_ROLLOUT_ORDER,
    get_balance_production_rollout,
    is_balance_action_enabled,
)


def test_production_default_rollout_is_enforced_off(monkeypatch) -> None:
    monkeypatch.delenv("BALANCE_ROLLOUT_STAGE", raising=False)
    monkeypatch.delenv("BALANCE_ROLLOUT_ENFORCED", raising=False)

    rollout = get_balance_production_rollout(environment="production")

    assert rollout.enforced
    assert rollout.stage == "off"
    assert rollout.enabled_actions == ()
    assert not is_balance_action_enabled("collect_dung", environment="production")


def test_blank_rollout_enforced_uses_environment_default(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "off")
    monkeypatch.setenv("BALANCE_ROLLOUT_ENFORCED", "")

    production_rollout = get_balance_production_rollout(environment="production")
    test_rollout = get_balance_production_rollout(environment="test")

    assert production_rollout.enforced
    assert not test_rollout.enforced
    assert not is_balance_action_enabled("collect_dung", environment="production")


def test_collect_dung_stage_enables_only_first_action(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "collect_dung")
    monkeypatch.setenv("BALANCE_ROLLOUT_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", "ops")

    rollout = get_balance_production_rollout(environment="production")

    assert rollout.order_valid
    assert rollout.blockers == ()
    assert rollout.enabled_actions == ("collect_dung",)
    assert is_balance_action_enabled("collect_dung", environment="production")
    assert not is_balance_action_enabled("deposit_cal", environment="production")


def test_blank_action_overrides_do_not_disable_stage_actions(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "collect_dung")
    monkeypatch.setenv("BALANCE_ROLLOUT_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ENABLE_COLLECT_DUNG", "")
    monkeypatch.setenv("BALANCE_ROLLOUT_ENABLE_WITHDRAW_CAL", "")

    rollout = get_balance_production_rollout(environment="production")

    assert rollout.order_valid
    assert rollout.blockers == ()
    assert rollout.enabled_actions == ("collect_dung",)
    assert is_balance_action_enabled("collect_dung", environment="production")


def test_public_stage_requires_owner_and_rollback_owner(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "collect_dung")
    monkeypatch.delenv("BALANCE_ROLLOUT_OWNER", raising=False)
    monkeypatch.delenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", raising=False)

    rollout = get_balance_production_rollout(environment="production")

    assert rollout.enabled_actions == ("collect_dung",)
    assert "balance_rollout_owner_missing" in rollout.blockers
    assert "balance_rollout_rollback_owner_missing" in rollout.blockers
    assert not is_balance_action_enabled("collect_dung", environment="production")


def test_later_action_override_without_prefix_blocks_rollout(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "off")
    monkeypatch.setenv("BALANCE_ROLLOUT_ENABLE_WITHDRAW_CAL", "true")
    monkeypatch.setenv("BALANCE_ROLLOUT_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", "ops")

    rollout = get_balance_production_rollout(environment="production")

    assert not rollout.order_valid
    assert "balance_rollout_order_invalid" in rollout.blockers
    assert not is_balance_action_enabled("withdraw_cal", environment="production")


def test_non_public_environment_does_not_block_local_route_calls(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "off")
    monkeypatch.delenv("BALANCE_ROLLOUT_ENFORCED", raising=False)

    assert is_balance_action_enabled("withdraw_to_wallet", environment="test")


def test_all_stage_preserves_explicit_rollout_order(monkeypatch) -> None:
    monkeypatch.setenv("BALANCE_ROLLOUT_STAGE", "all")
    monkeypatch.setenv("BALANCE_ROLLOUT_OWNER", "ops")
    monkeypatch.setenv("BALANCE_ROLLOUT_ROLLBACK_OWNER", "ops")

    rollout = get_balance_production_rollout(environment="production")

    assert rollout.enabled_actions == BALANCE_ROLLOUT_ORDER
    assert [action.key for action in rollout.actions] == list(BALANCE_ROLLOUT_ORDER)
