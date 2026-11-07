"""Shared helpers for provider-backed ride imports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional
from uuid import UUID

from .ride_ingest import RideIngestJob, enqueue_ride_ingest


@dataclass(frozen=True)
class PendingProviderRideRequeue:
    attempted: bool
    accepted: bool
    ride_id: Optional[str] = None
    error: Optional[str] = None


async def requeue_pending_provider_ride(
    *,
    ride_repo: Any,
    user_repo: Any,
    ride: dict[str, Any],
    wallet: str,
    user_id: str,
    default_file_type: str,
    enqueue_source: str,
    source_id: str,
) -> PendingProviderRideRequeue:
    """Re-enqueue an existing pending provider ride without creating a duplicate row."""
    ride_id = str(ride.get("id") or "")
    if not ride_id:
        return PendingProviderRideRequeue(
            attempted=True,
            accepted=False,
            error="Existing provider ride is missing an id",
        )

    if str(ride.get("processing_status") or "") != "pending":
        return PendingProviderRideRequeue(attempted=False, accepted=False, ride_id=ride_id)

    full_ride = await ride_repo.get_ride(ride_id)
    file_path = (full_ride or ride).get("raw_file_path")
    file_type = (full_ride or ride).get("file_type") or default_file_type
    if not file_path:
        return PendingProviderRideRequeue(
            attempted=True,
            accepted=False,
            ride_id=ride_id,
            error=f"Pending provider ride {ride_id} missing raw_file_path",
        )

    profile = await user_repo.get_user_profile(wallet)
    user_weight = float(profile.get("weight_kg") or 75.0) if profile else 75.0
    enqueue_result = await enqueue_ride_ingest(
        RideIngestJob(
            ride_id=ride_id,
            wallet=wallet,
            user_id=str(user_id),
            file_type=file_type,
            file_path=file_path,
            user_weight_kg=user_weight,
            source=enqueue_source,
            source_id=str(source_id),
        )
    )
    if not enqueue_result.accepted:
        return PendingProviderRideRequeue(
            attempted=True,
            accepted=False,
            ride_id=ride_id,
            error=enqueue_result.error or "Processing queue unavailable",
        )

    await ride_repo.update_ride_status(UUID(ride_id), "processing")
    return PendingProviderRideRequeue(attempted=True, accepted=True, ride_id=ride_id)
