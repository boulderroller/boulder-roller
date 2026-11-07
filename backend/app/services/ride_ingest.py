"""
Canonical ride-ingest enqueue helpers.

NATS JetStream is the sole ride-processing queue. Celery/Redis have been
removed from the infrastructure.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional

from .nats_client import get_nats_client

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RideIngestJob:
    """Canonical ride-processing job envelope."""

    ride_id: str
    user_id: str
    wallet: str
    file_type: str
    file_path: str
    user_weight_kg: float
    source: str
    source_id: Optional[str] = None
    reprocess: bool = False

    def to_payload(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "ride_id": self.ride_id,
            "wallet": self.wallet,
            "user_id": self.user_id,
            "file_type": self.file_type,
            "file_path": self.file_path,
            "user_weight_kg": self.user_weight_kg,
            "source": self.source,
            "reprocess": self.reprocess,
        }
        if self.source_id is not None:
            payload["source_id"] = self.source_id
        return payload


@dataclass(frozen=True)
class RideIngestEnqueueResult:
    """Outcome of enqueueing a ride-processing job."""

    accepted: bool
    backend: str
    error: Optional[str] = None


async def enqueue_ride_ingest(job: RideIngestJob) -> RideIngestEnqueueResult:
    """Publish a ride-processing job to NATS JetStream."""
    client = get_nats_client()
    published = await client.publish("rides.events.uploaded", job.to_payload())
    if published:
        return RideIngestEnqueueResult(accepted=True, backend="nats")

    return RideIngestEnqueueResult(
        accepted=False,
        backend="nats",
        error="NATS unavailable",
    )
