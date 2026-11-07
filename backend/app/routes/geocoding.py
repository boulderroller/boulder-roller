"""Authenticated, explicit-submit place-search route."""
from __future__ import annotations

import asyncio
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel, Field

from ..config import load_geocoder_settings
from ..dependencies import AuthenticatedUser, get_current_user
from ..middleware.rate_limiter import rate_limit
from ..services.geocoding import (
    GeocodingQueryError,
    GeocodingService,
    GeocodingUnavailable,
    SharedGeocodingCache,
    normalize_geocoding_query,
)


router = APIRouter(tags=["geocoding"])

_geocoding_service: Optional[GeocodingService] = None
_geocoding_service_lock: Optional[asyncio.Lock] = None


class GeocodingSearchRequest(BaseModel):
    query: str


class GeocodingResult(BaseModel):
    display_name: str = Field(alias="displayName")
    latitude: float
    longitude: float

    model_config = {"populate_by_name": True}


class GeocodingAttribution(BaseModel):
    text: str
    url: str


class GeocodingSearchResponse(BaseModel):
    contract_version: Literal["geocoding.v1"] = Field(alias="contractVersion")
    state: Literal["available"]
    results: list[GeocodingResult]
    attribution: GeocodingAttribution
    provider: Literal["nominatim"]
    cached: bool

    model_config = {"populate_by_name": True}


async def get_geocoding_service() -> GeocodingService:
    """Return the one event-loop singleton that owns provider request pacing."""
    global _geocoding_service, _geocoding_service_lock

    if _geocoding_service is not None:
        return _geocoding_service

    # FastAPI executes async dependencies on the application event loop. Lock
    # creation has no intervening await, so cold concurrent requests share this
    # one initialization gate instead of racing through duplicate services.
    if _geocoding_service_lock is None:
        _geocoding_service_lock = asyncio.Lock()
    async with _geocoding_service_lock:
        if _geocoding_service is None:
            _geocoding_service = GeocodingService(
                settings=load_geocoder_settings(),
                cache=SharedGeocodingCache(),
            )
        return _geocoding_service


@router.post("/search", response_model=GeocodingSearchResponse)
@rate_limit(category="geocoding")
async def search_places(
    request: Request,
    payload: GeocodingSearchRequest,
    current_user: AuthenticatedUser = Depends(get_current_user),
    service: GeocodingService = Depends(get_geocoding_service),
) -> dict:
    del current_user  # Authentication is the authorization boundary for this route.
    try:
        query = normalize_geocoding_query(payload.query)
    except GeocodingQueryError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "invalid_place_query"},
        ) from None

    try:
        return await service.search(query)
    except GeocodingUnavailable:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "place_search_unavailable"},
        ) from None
