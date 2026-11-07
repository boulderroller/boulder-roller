import hashlib
from typing import Any, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, status

from ..dependencies import (
    AuthenticatedUser,
    get_current_user,
    get_repository,
    get_ride_repository,
)
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository, RideRepository
from ..schemas import ProofVerifyRequest, ProofVerifyResponse
from ..security.siws import verify_siws_signature
from ..services.reward_threshold import (
    parse_threshold_rider_projection,
    project_threshold_training_tss,
)

router = APIRouter()


def _coerce_float(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _build_proof_verification_message(*, wallet: str, ride: dict[str, Any], effort_score: float) -> str:
    """Canonical wallet-signed payload for legacy proof verification."""
    return "\n".join(
        [
            "BoulderRollers wants you to verify a ride proof",
            f"wallet: {wallet}",
            f"ride_id: {ride.get('id') or ''}",
            f"user_id: {ride.get('user_id') or ''}",
            f"ride_hash: {ride.get('ride_hash_hex') or ''}",
            f"attestation_commitment: {ride.get('attestation_commitment_hex') or ''}",
            f"effort_score: {effort_score:.2f}",
        ]
    )


async def _derived_threshold_effort_score(
    *,
    ride_repo: RideRepository,
    user_id: str,
    ride: dict[str, Any],
) -> float:
    """Derive a new proof score only from post-cutover Threshold authority."""
    if ride.get("threshold_training_kind") not in {"sealed", "pending"}:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "threshold_training_unavailable"},
        )
    if (
        ride.get("normalized_power_raw_w") is None
        and ride.get("normalized_power_w") is None
    ) or ride.get("normalized_power_duration_s") is None:
        # The shared display projection may retain a post-cutover stored TSS
        # for non-power rides. A new durable proof has a stricter contract: it
        # must be recomputable so the current Threshold actually enters its
        # signed score.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "threshold_training_unavailable"},
        )
    try:
        raw = await ride_repo.get_reward_threshold_rider_projection(user_id)
        projection = parse_threshold_rider_projection(raw)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "threshold_authority_unavailable"},
        ) from exc
    if (
        projection.state != "established"
        or projection.training_denominator.kind != "sealed"
    ):
        # A scheduled Monday value is provisional. Do not freeze it into a
        # durable verified proof before it becomes sealed authority.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "threshold_training_unavailable"},
        )
    score = project_threshold_training_tss(
        ride,
        threshold_w=projection.training_denominator.watts,
    )
    if score is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "threshold_training_unavailable"},
        )
    return score


@router.post("/verify", response_model=ProofVerifyResponse)
@rate_limit(category="token_mint")
async def verify_proof(
    payload: ProofVerifyRequest,
    request: Request,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    ride_repo: RideRepository = Depends(get_ride_repository),
) -> ProofVerifyResponse:
    """Read existing proofs or create one from sealed Threshold authority."""
    ride = await repo.get_ride(str(payload.ride_id))
    if not ride:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ride not found")
    if ride.get("user_id") != current_user.user_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your ride")

    existing = await repo.get_proof_for_ride(str(payload.ride_id))
    if existing:
        if existing.get("user_id") and existing["user_id"] != current_user.user_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not your proof")
        proof_id = existing["id"]
        effort_score = _coerce_float(existing.get("effort_score"))
        if effort_score is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "proof_authority_unavailable"},
            )
        return ProofVerifyResponse(proof_id=UUID(str(proof_id)), effort_score=effort_score)

    effort_score = await _derived_threshold_effort_score(
        ride_repo=ride_repo,
        user_id=current_user.user_id,
        ride=ride,
    )
    signed_ride = {**ride, "id": ride.get("id") or str(payload.ride_id)}
    message = _build_proof_verification_message(
        wallet=current_user.wallet,
        ride=signed_ride,
        effort_score=effort_score,
    )
    try:
        verify_siws_signature(current_user.wallet, payload.signature, message)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid proof signature",
        ) from exc

    proof_id = await repo.create_proof(
        ride_id=str(payload.ride_id),
        effort_score=effort_score,
        signature=payload.signature,
        proof_hash=hashlib.sha256(message.encode("utf-8")).hexdigest(),
        user_id=current_user.user_id,
        status="verified",
    )
    return ProofVerifyResponse(proof_id=UUID(str(proof_id)), effort_score=effort_score)
