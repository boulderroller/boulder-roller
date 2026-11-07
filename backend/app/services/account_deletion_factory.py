"""Canonical construction for the destructive account-deletion authority."""

from __future__ import annotations

from typing import Any

from .. import solana_direct
from .account_deletion import AccountDeletionAuthorityReader


def build_account_deletion_authority_reader(
    repository: Any,
) -> AccountDeletionAuthorityReader:
    """Build the one reader shared by HTTP preflight and the worker gate."""
    return AccountDeletionAuthorityReader(
        repository=repository,
        balance_snapshot_loader=solana_direct.get_rider_balance_account_snapshot,
        balance_dung_loader=solana_direct.get_finalized_balance_dung_balance_source,
        stake_loader=solana_direct.get_rider_vault_stake_accounts,
    )
