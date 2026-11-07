"""Shared policy for Vaults allowed to accept new economic state."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Optional


REWARD_AUTHORITATIVE_SEED_GENERATION = 2


def _field(vault: Any, name: str) -> Any:
    if isinstance(vault, Mapping):
        return vault.get(name)
    return getattr(vault, name, None)


def _seed_generation(vault: Any) -> Optional[int]:
    value = _field(vault, "chain_activation_seed_generation")
    if isinstance(value, bool):
        return None
    try:
        generation = int(value)
    except (TypeError, ValueError):
        return None
    return generation if generation >= 0 else None


def is_reward_authoritative_vault(vault: Any) -> bool:
    """Return whether chain-derived activation may accept new economics."""
    if vault is None or _field(vault, "chain_activation_active") is not True:
        return False
    generation = _seed_generation(vault)
    return (
        generation is not None
        and generation >= REWARD_AUTHORITATIVE_SEED_GENERATION
    )
