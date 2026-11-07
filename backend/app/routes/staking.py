"""Legacy staking compatibility routes.

Canonical staking operations live under vault routes and portfolio projections.
This module keeps older clients from breaking while boulderroller-v2-ejy8 tracks
retirement of compatibility shims.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Response

from ..dependencies import AuthenticatedUser, get_current_user, get_repository
from ..repositories import DatabaseRepository

router = APIRouter()


def _to_legacy_claim(user_id: str, claim: dict[str, Any]) -> dict[str, Any]:
    segment_id_raw = claim.get("segment_id") or claim.get("vault_id")
    claim_key = segment_id_raw if segment_id_raw is not None else claim.get("id", "unknown")
    try:
        segment_id = int(segment_id_raw)
    except (TypeError, ValueError):
        segment_id = segment_id_raw

    return {
        "claim_id": claim.get("claim_id") or f"{user_id}:{claim_key}",
        "segment_id": segment_id,
        "vault_id": claim.get("vault_id"),
        "amount": claim.get("amount") or claim.get("amount_staked"),
        "lp_tokens": claim.get("lp_tokens"),
        "staked_at": claim.get("staked_at"),
    }


@router.get("/claims", deprecated=True)
async def get_legacy_staking_claims(
    response: Response,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
) -> dict[str, Any]:
    """Return legacy staking claims for pre-vault client builds."""
    response.headers["Deprecation"] = "true"
    response.headers["X-BoulderRoller-Compatibility-Tracker"] = "boulderroller-v2-ejy8"
    claims = await repo.get_user_claims(current_user.user_id)
    return {
        "claims": [
            _to_legacy_claim(current_user.user_id, claim)
            for claim in claims
        ],
        "total_claims": len(claims),
    }
