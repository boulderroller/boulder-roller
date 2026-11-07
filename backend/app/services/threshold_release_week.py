"""Validate the immutable Settlement Week for one held-ride release."""

from __future__ import annotations

from typing import Any, Awaitable, Callable, Optional

from solders.pubkey import Pubkey

from .chain_receipt_execution import authoritative_chain_clock
from .protocol_ints import U64_MAX, exact_uint
from .ride_chain_accounts import (
    AccountReader,
    ChainAccountMismatchError,
    decode_held_ride_release_authority,
    read_owned_account,
)


VaultAccountReader = Callable[..., Awaitable[Optional[dict[str, Any]]]]


class ThresholdReleaseFlowNotOpen(RuntimeError):
    """The Vault or release flow cannot yet be read for safe submission."""


async def require_frozen_release_week(
    *,
    config: Any,
    release: Pubkey,
    ride_attestation: Pubkey,
    rider: Pubkey,
    vault_id: int,
    account_reader: AccountReader,
    vault_account_reader: VaultAccountReader,
) -> tuple[str, int]:
    """Allow equal or lagging Vaults; the instruction advances only empty lag."""
    release_raw = await read_owned_account(
        reader=account_reader,
        rpc_url=config.rpc_url,
        address=release,
        program_id=config.program_id,
    )
    release_account = decode_held_ride_release_authority(release_raw.data)
    if (
        release_account.ride_attestation != ride_attestation
        or release_account.rider != rider
    ):
        raise ChainAccountMismatchError(
            "held release authority does not match released completion"
        )
    release_confirmed_at = authoritative_chain_clock(
        release_account.released_at,
        field="HeldRideReleaseAuthority.released_at",
    )
    vault_account = await vault_account_reader(config, vault_id)
    if not isinstance(vault_account, dict):
        raise ThresholdReleaseFlowNotOpen(
            f"Vault {vault_id} is unavailable for release-week validation"
        )
    vault_week = exact_uint(
        vault_account.get("open_settlement_week"),
        field="vault.open_settlement_week",
        maximum=U64_MAX,
    )
    release_week = exact_uint(
        release_account.release_settlement_week,
        field="release.release_settlement_week",
        maximum=U64_MAX,
    )
    if vault_week > release_week:
        raise ChainAccountMismatchError(
            f"Vault {vault_id} flow {vault_week} has passed release week {release_week}"
        )
    return release_confirmed_at, release_week
