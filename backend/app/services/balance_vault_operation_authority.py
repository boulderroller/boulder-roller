"""Exact intent contract for rider-authorized Balance-funded Vault actions."""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from enum import IntEnum

from solders.pubkey import Pubkey


BALANCE_VAULT_OPERATION_DOMAIN = b"BR_BALANCE_VAULT_OPERATION_V1"
U64_MAX = (1 << 64) - 1
I64_MAX = (1 << 63) - 1


class BalanceVaultOperationKind(IntEnum):
    CREATE_VAULT = 0
    DEPOSIT_CAL = 1
    WITHDRAW_CAL = 2


@dataclass(frozen=True)
class BalanceVaultOperationAuthorization:
    operation_id: bytes
    generation: int
    nonce: int
    expires_at: int

    def __post_init__(self) -> None:
        if len(self.operation_id) != 32 or self.operation_id == bytes(32):
            raise ValueError("operation_id must be exactly 32 non-zero bytes")
        _require_u64("generation", self.generation)
        _require_u64("nonce", self.nonce)
        if not isinstance(self.expires_at, int) or not 0 < self.expires_at <= I64_MAX:
            raise ValueError("expires_at must be a positive signed 64-bit Unix timestamp")

    def encode(self) -> bytes:
        """Encode the Anchor struct using its Borsh field order."""

        return (
            self.operation_id
            + struct.pack("<Q", self.generation)
            + struct.pack("<Q", self.nonce)
            + struct.pack("<q", self.expires_at)
        )


def derive_balance_vault_operation_id(
    *,
    program_id: Pubkey,
    rider: Pubkey,
    operation_authority: Pubkey,
    kind: BalanceVaultOperationKind,
    vault_id: int,
    primary_amount: int,
    secondary_amount: int,
    generation: int,
    nonce: int,
    expires_at: int,
) -> bytes:
    """Match the program's SHA-256 intent binding byte-for-byte."""

    _require_u64("vault_id", vault_id)
    _require_u64("primary_amount", primary_amount)
    _require_u64("secondary_amount", secondary_amount)
    _require_u64("generation", generation)
    _require_u64("nonce", nonce)
    if not isinstance(expires_at, int) or not 0 < expires_at <= I64_MAX:
        raise ValueError("expires_at must be a positive signed 64-bit Unix timestamp")

    return hashlib.sha256(
        b"".join(
            (
                BALANCE_VAULT_OPERATION_DOMAIN,
                bytes(program_id),
                bytes(rider),
                bytes(operation_authority),
                bytes((int(kind),)),
                struct.pack("<Q", vault_id),
                struct.pack("<Q", primary_amount),
                struct.pack("<Q", secondary_amount),
                struct.pack("<Q", generation),
                struct.pack("<Q", nonce),
                struct.pack("<q", expires_at),
            )
        )
    ).digest()


def build_balance_vault_operation_authorization(
    *,
    program_id: Pubkey,
    rider: Pubkey,
    operation_authority: Pubkey,
    kind: BalanceVaultOperationKind,
    vault_id: int,
    primary_amount: int,
    secondary_amount: int,
    generation: int,
    nonce: int,
    expires_at: int,
) -> BalanceVaultOperationAuthorization:
    return BalanceVaultOperationAuthorization(
        operation_id=derive_balance_vault_operation_id(
            program_id=program_id,
            rider=rider,
            operation_authority=operation_authority,
            kind=kind,
            vault_id=vault_id,
            primary_amount=primary_amount,
            secondary_amount=secondary_amount,
            generation=generation,
            nonce=nonce,
            expires_at=expires_at,
        ),
        generation=generation,
        nonce=nonce,
        expires_at=expires_at,
    )


def _require_u64(name: str, value: int) -> None:
    if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= U64_MAX:
        raise ValueError(f"{name} must be an unsigned 64-bit integer")
