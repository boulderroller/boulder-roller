"""
Token metadata endpoints for Solana token standards.
Serves JSON metadata for DUNG token and future tokens.
"""
import logging
import os
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse

from ..dependencies import AuthenticatedUser, get_optional_current_user
from ..metrics import WEB_VITAL_CLS_VALUE, WEB_VITAL_SAMPLES, WEB_VITAL_VALUE_MS
from ..middleware.metrics import normalize_path
from ..middleware.rate_limiter import rate_limit
from ..schemas import WebVitalsIngestRequest, WebVitalsIngestResponse

router = APIRouter(prefix="/metadata", tags=["metadata"])
logger = logging.getLogger(__name__)

# DUNG token metadata following Metaplex standard
DUNG_METADATA = {
    "name": "DUNG",
    "symbol": "DUNG",
    "description": "Boulder Rollers ride reward token. Earned by completing cycling activities with verified GPS data on the Solana blockchain.",
    "image": "https://api.boulderroller.xyz/metadata/dung-logo.svg",
    "external_url": "https://boulderroller.xyz",
    "attributes": [
        {"trait_type": "Category", "value": "Utility Token"},
        {"trait_type": "Ecosystem", "value": "Boulder Rollers"},
        {"trait_type": "Earning Method", "value": "Ride-to-Earn"},
    ],
    "properties": {
        "files": [
            {
                "uri": "https://api.boulderroller.xyz/metadata/dung-logo.svg",
                "type": "image/svg+xml",
            }
        ],
        "category": "currency",
    },
}


@router.get("/dung.json")
async def get_dung_metadata():
    """Return DUNG token metadata in Metaplex standard format."""
    return JSONResponse(
        content=DUNG_METADATA,
        headers={
            "Cache-Control": "public, max-age=86400",
            "Access-Control-Allow-Origin": "*",
        },
    )


@router.get("/dung-logo.png")
async def get_dung_logo():
    """Compatibility route for older metadata that referenced a PNG path."""
    svg_path = os.path.join(os.path.dirname(__file__), "../static/dung-logo.svg")
    if os.path.exists(svg_path):
        return RedirectResponse(url="/metadata/dung-logo.svg", status_code=302)
    # Fallback to beetle emoji
    return RedirectResponse(
        url="https://em-content.zobj.net/source/twitter/376/beetle_1fab2.png",
        status_code=302,
    )


@router.get("/dung-logo.svg")
async def get_dung_logo_svg():
    """Return DUNG token logo as SVG."""
    svg_path = os.path.join(os.path.dirname(__file__), "../static/dung-logo.svg")
    return FileResponse(
        svg_path,
        media_type="image/svg+xml",
        headers={"Cache-Control": "public, max-age=86400"},
    )


def _normalize_route_label(route: str) -> str:
    if not route:
        return "/"
    stripped = route.split("?", 1)[0].strip()
    if not stripped:
        return "/"
    path = stripped if stripped.startswith("/") else f"/{stripped}"
    normalized = normalize_path(path)
    return normalized[:120]


def _normalize_rating_label(rating: Optional[str]) -> str:
    if not rating:
        return "unrated"
    compact = rating.strip().lower().replace("-", "_").replace(" ", "_")
    if compact in {"good", "needs_improvement", "poor"}:
        return compact
    return "unrated"


@router.post("/web-vitals", response_model=WebVitalsIngestResponse)
@rate_limit(category="telemetry")
async def ingest_web_vitals(
    payload: WebVitalsIngestRequest,
    request: Request,
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
) -> WebVitalsIngestResponse:
    accepted = 0
    dropped = 0

    for sample in payload.metrics:
        route_label = _normalize_route_label(sample.route)
        rating_label = _normalize_rating_label(sample.rating)
        metric_label = sample.metric

        WEB_VITAL_SAMPLES.labels(
            metric=metric_label,
            route=route_label,
            device=sample.device,
            rating=rating_label,
        ).inc()

        if metric_label == "cls":
            WEB_VITAL_CLS_VALUE.labels(route=route_label, device=sample.device).observe(sample.value)
        else:
            WEB_VITAL_VALUE_MS.labels(metric=metric_label, route=route_label, device=sample.device).observe(sample.value)

        accepted += 1

    logger.info(
        "Ingested %s web-vital samples",
        accepted,
        extra={
            "path": request.url.path,
            "sampled": payload.sampled,
            "user_id": current_user.user_id if current_user else None,
            "dropped": dropped,
        },
    )
    return WebVitalsIngestResponse(accepted=accepted, dropped=dropped)
