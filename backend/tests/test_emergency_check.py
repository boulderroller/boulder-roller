from app.middleware.emergency_check import EmergencyCheckMiddleware


def test_emergency_controls_cover_vault_economy_routes() -> None:
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/stake") == "staking_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/stake/prepare") == "staking_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/unstake") == "withdrawals_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/unstake/prepare") == "withdrawals_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/harvest") == "withdrawals_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/vaults/12/harvest/prepare") == "withdrawals_enabled"


def test_emergency_controls_prioritize_legacy_unstake_withdrawal_route() -> None:
    assert EmergencyCheckMiddleware.control_for_path("/staking/unstake") == "withdrawals_enabled"
    assert EmergencyCheckMiddleware.control_for_path("/staking/123") == "staking_enabled"
