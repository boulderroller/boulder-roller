"""Waitlist endpoint for landing-page email capture."""

import hashlib
import logging
import re
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator

from ..dependencies import get_repository
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository

router = APIRouter()

EMAIL_REGEX = re.compile(r"^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$")
logger = logging.getLogger(__name__)


class WaitlistRequest(BaseModel):
    email: str = Field(..., min_length=5, max_length=320)
    source: Optional[str] = Field(default="landing", max_length=50)

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        email = value.strip().lower()
        if not EMAIL_REGEX.match(email):
            raise ValueError("Invalid email format")
        return email


class WaitlistResponse(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    contract_version: Literal["waitlist.v1"] = Field(default="waitlist.v1", alias="contractVersion")
    status: str
    state: Literal["accepted"]
    message: str
    email: str
    source: str
    submitted_at: Optional[str] = Field(default=None, alias="submittedAt")


@router.post("/waitlist", response_model=WaitlistResponse)
@rate_limit(category="waitlist")
async def add_to_waitlist(
    request: Request,
    payload: WaitlistRequest,
    repo: DatabaseRepository = Depends(get_repository),
) -> WaitlistResponse:
    """Public compatibility endpoint still used by the legacy landing page."""
    try:
        client_ip = request.client.host if request.client else "unknown"
        entry = await repo.add_to_waitlist(
            email=payload.email,
            source=payload.source or "landing",
            ip_hash=int(hashlib.sha256(client_ip.encode("utf-8")).hexdigest()[:16], 16) % (10**18),
        )
    except Exception as exc:
        logger.error("Waitlist signup failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Waitlist signup is temporarily unavailable",
        ) from exc

    return WaitlistResponse(
        status="success",
        state="accepted",
        message="Request received",
        email=str(entry.get("email") or payload.email),
        source=str(entry.get("source") or payload.source or "landing"),
        submitted_at=entry.get("created_at"),
    )
