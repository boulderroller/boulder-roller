from __future__ import annotations

import struct

import pytest
from solders.pubkey import Pubkey

from app.services.balance_vault_operation_authority import (
    BalanceVaultOperationAuthorization,
    BalanceVaultOperationKind,
    build_balance_vault_operation_authorization,
    derive_balance_vault_operation_id,
)


PROGRAM_ID = Pubkey.from_string("EVjP2Vdz9buHNphywPhoybf213poa8EiSW6FGbXWFqYH")
RIDER = Pubkey.from_string("Ch8uwuNxXkQBTJfBNbCq57yhaKdADCTiLLHqzb7G9uXF")
AUTHORITY = Pubkey.from_string("9h6UJdZqUPNnShaUHkSoxvEeZ7gBeNxzXGQcShhBnzEP")


def _fields() -> dict[str, object]:
    return {
        "program_id": PROGRAM_ID,
        "rider": RIDER,
        "operation_authority": AUTHORITY,
        "kind": BalanceVaultOperationKind.DEPOSIT_CAL,
        "vault_id": 7,
        "primary_amount": 5_000_000_000,
        "secondary_amount": 0,
        "generation": 3,
        "nonce": 7,
        "expires_at": 1_800_000_000,
    }


def test_operation_id_matches_frozen_rust_vector() -> None:
    assert derive_balance_vault_operation_id(**_fields()).hex() == (
        "bf6a066a6233732a6d6751e27abec213b2e9fdd5f6352ffb08910d1e04688749"
    )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("rider", AUTHORITY),
        ("operation_authority", RIDER),
        ("kind", BalanceVaultOperationKind.WITHDRAW_CAL),
        ("vault_id", 8),
        ("primary_amount", 5_000_000_001),
        ("secondary_amount", 1),
        ("generation", 4),
        ("nonce", 8),
        ("expires_at", 1_800_000_001),
    ),
)
def test_operation_id_binds_every_authority_and_economic_field(
    field: str,
    value: object,
) -> None:
    fields = _fields()
    expected = derive_balance_vault_operation_id(**fields)
    fields[field] = value

    assert derive_balance_vault_operation_id(**fields) != expected


def test_authorization_encoding_matches_anchor_borsh_layout() -> None:
    authorization = build_balance_vault_operation_authorization(**_fields())

    assert authorization.encode() == (
        authorization.operation_id
        + struct.pack("<Q", 3)
        + struct.pack("<Q", 7)
        + struct.pack("<q", 1_800_000_000)
    )
    assert len(authorization.encode()) == 56


def test_authorization_rejects_zero_operation_id() -> None:
    with pytest.raises(ValueError, match="operation_id"):
        BalanceVaultOperationAuthorization(
            operation_id=bytes(32),
            generation=1,
            nonce=0,
            expires_at=1_800_000_000,
        )
