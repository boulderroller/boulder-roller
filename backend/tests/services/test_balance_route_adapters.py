from __future__ import annotations

import pytest

from app.services.balance_route_adapters import (
    BalanceRouteAdapter,
    PortfolioBalanceRouteScope,
    VaultBalanceRouteScope,
    add_funds_intent,
    collect_dung_intent,
    create_vault_intent,
    deposit_cal_intent,
    withdraw_to_wallet_intent,
    withdraw_cal_intent,
)
from app.services.boulder_balance_authority import AuthorityModel


def _scope(
    *,
    prepared_message_hash: str = "hash-123",
    client_request_id: str | None = None,
) -> VaultBalanceRouteScope:
    return VaultBalanceRouteScope(
        rider_account_id="rider-123",
        protocol_wallet="7rider",
        vault_id=42,
        vault_signature="ab" * 64,
        prepared_message_hash=prepared_message_hash,
        client_request_id=client_request_id,
        metadata={"surface": "vault"},
    )


def _portfolio_scope() -> PortfolioBalanceRouteScope:
    return PortfolioBalanceRouteScope(
        rider_account_id="rider-123",
        protocol_wallet="7rider",
        prepared_message_hash="hash-123",
        client_request_id="client-123",
        metadata={"surface": "portfolio"},
    )


def test_add_funds_uses_portfolio_wallet_boundary_adapter() -> None:
    intent = add_funds_intent(
        scope=_portfolio_scope(),
        asset="cal",
        amount="250000000",
        destination="RiderBalance CAL token PDA",
    )

    assert intent.action_type == "add_funds"
    assert intent.authority_model is AuthorityModel.WALLET_BOUNDARY
    assert intent.asset == "CAL"
    assert intent.source == "wallet:7rider:cal"
    assert intent.destination == "RiderBalance CAL token PDA"
    assert intent.step_up_satisfied
    assert intent.reference_type == "portfolio_balance"
    assert intent.metadata["adapter"] == BalanceRouteAdapter.ADD_FUNDS_TO_BALANCE.value
    assert intent.metadata["client_request_id"] == "client-123"


def test_withdraw_to_wallet_uses_portfolio_wallet_boundary_adapter() -> None:
    intent = withdraw_to_wallet_intent(
        scope=_portfolio_scope(),
        asset="dung",
        amount="1000",
        source="RiderBalance DUNG token PDA",
    )

    assert intent.action_type == "withdraw_to_wallet"
    assert intent.authority_model is AuthorityModel.WALLET_BOUNDARY
    assert intent.asset == "DUNG"
    assert intent.source == "RiderBalance DUNG token PDA"
    assert intent.destination == "wallet:7rider:dung"
    assert intent.metadata["adapter"] == BalanceRouteAdapter.WITHDRAW_TO_WALLET.value


def test_collect_dung_uses_permissionless_for_rider_adapter() -> None:
    intent = collect_dung_intent(
        scope=_scope(),
        amount="950",
        destination="DungWalletAta111",
        fee_payer="fee-payer",
    )

    assert intent.action_type == "collect_dung"
    assert intent.authority_model is AuthorityModel.PERMISSIONLESS_FOR_RIDER
    assert intent.asset == "DUNG"
    assert intent.source == "vault:42:stake_rewards"
    assert intent.destination == "DungWalletAta111"
    assert intent.fee_payer == "fee-payer"
    assert intent.metadata["adapter"] == BalanceRouteAdapter.COLLECT_DUNG_FOR_RIDER.value
    assert intent.metadata["boundary_fallback"] == "false"
    assert intent.metadata["destination_type"] == "spl_wallet_ata"
    assert intent.metadata["destination_owner"] == "7rider"


def test_deposit_cal_can_use_balance_instruction_adapter() -> None:
    intent = deposit_cal_intent(
        scope=_scope(),
        amount="250000000000",
        use_balance=True,
        rider_session_id="rider-session-123",
    )

    assert intent.authority_model is AuthorityModel.RIDER_SESSION
    assert intent.policy_or_delegate_id == "rider-session-123"
    assert intent.source == "RiderBalance CAL token PDA"
    assert intent.destination == "vault:42:cal_escrow"
    assert intent.metadata["adapter"] == BalanceRouteAdapter.DEPOSIT_CAL_FROM_BALANCE.value
    assert intent.metadata["boundary_fallback"] == "false"


def test_withdraw_cal_can_use_balance_instruction_adapter() -> None:
    intent = withdraw_cal_intent(
        scope=_scope(),
        amount="100000000000",
        use_balance=True,
        rider_session_id="rider-session-123",
    )

    assert intent.authority_model is AuthorityModel.RIDER_SESSION
    assert intent.policy_or_delegate_id == "rider-session-123"
    assert intent.source == "vault:42:balance_lp"
    assert intent.destination == "RiderBalance CAL token PDA"
    assert intent.metadata["adapter"] == BalanceRouteAdapter.WITHDRAW_CAL_TO_BALANCE.value
    assert intent.metadata["boundary_fallback"] == "false"


@pytest.mark.parametrize("action", ("deposit", "withdraw"))
def test_balance_funded_vault_actions_reject_missing_rider_session(action: str) -> None:
    with pytest.raises(ValueError, match="require a rider_session_id"):
        if action == "deposit":
            deposit_cal_intent(scope=_scope(), amount="1", use_balance=True)
        else:
            withdraw_cal_intent(scope=_scope(), amount="1", use_balance=True)


def test_wallet_signed_paths_are_explicit_boundary_fallbacks() -> None:
    deposit = deposit_cal_intent(scope=_scope(), amount="250000000000")
    withdraw = withdraw_cal_intent(scope=_scope(), amount="100000000000")
    create = create_vault_intent(
        scope=_scope(),
        amount="1000",
        payment_method="dung",
        destination="vault-pda-42",
    )

    assert deposit.authority_model is AuthorityModel.WALLET_BOUNDARY
    assert withdraw.authority_model is AuthorityModel.WALLET_BOUNDARY
    assert create.authority_model is AuthorityModel.WALLET_BOUNDARY
    assert deposit.step_up_satisfied
    assert withdraw.step_up_satisfied
    assert create.step_up_satisfied
    assert deposit.metadata["adapter"] == BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK.value
    assert withdraw.metadata["adapter"] == BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK.value
    assert create.metadata["adapter"] == BalanceRouteAdapter.WALLET_BOUNDARY_FALLBACK.value
    assert deposit.metadata["boundary_fallback"] == "true"
    assert withdraw.metadata["boundary_fallback"] == "true"
    assert create.metadata["boundary_fallback"] == "true"


def test_vault_intent_identity_tracks_the_prepared_message() -> None:
    first = deposit_cal_intent(
        scope=_scope(prepared_message_hash="message-a"),
        amount="250000000000",
    )
    replay = deposit_cal_intent(
        scope=_scope(prepared_message_hash="message-a"),
        amount="250000000000",
    )
    later_action = deposit_cal_intent(
        scope=_scope(prepared_message_hash="message-b"),
        amount="250000000000",
    )

    assert first.idempotency_key == replay.idempotency_key
    assert first.idempotency_key != later_action.idempotency_key


def test_client_request_identity_overrides_blockhash_churn_for_an_exact_retry() -> None:
    first = deposit_cal_intent(
        scope=_scope(
            prepared_message_hash="message-a",
            client_request_id="request-1",
        ),
        amount="250000000000",
    )
    retried_after_reprepare = deposit_cal_intent(
        scope=_scope(
            prepared_message_hash="message-b",
            client_request_id="request-1",
        ),
        amount="250000000000",
    )
    later_action = deposit_cal_intent(
        scope=_scope(
            prepared_message_hash="message-b",
            client_request_id="request-2",
        ),
        amount="250000000000",
    )

    assert first.idempotency_key == retried_after_reprepare.idempotency_key
    assert first.idempotency_key != later_action.idempotency_key
