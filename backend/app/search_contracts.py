"""Canonical search.v1 contracts for app-wide discovery.

Search is a projected read contract: it helps clients navigate to rider, ride,
climb, and proof surfaces without becoming authoritative for protocol state.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from .link_contracts import LinkTargetType, canonical_web_path
from .target_action_contracts import (
    TargetRef,
    capabilities_for_target,
    primary_action_for_target,
    target_ref_dict,
)


SEARCH_CONTRACT_VERSION = "search.v1"

BASE58_RE = re.compile(r"^[1-9A-HJ-NP-Za-km-z]+$")
USERNAME_RE = re.compile(r"^@?[a-z0-9_-]{3,20}$", re.IGNORECASE)


class SearchType(str, Enum):
    all = "all"
    riders = "riders"
    rides = "rides"
    climbs = "climbs"
    proofs = "proofs"


class SearchResultType(str, Enum):
    rider = "rider"
    ride = "ride"
    climb = "climb"
    proof = "proof"


class SearchTarget(TargetRef):
    pass


class SearchStat(BaseModel):
    label: str
    value: str


class SearchImage(BaseModel):
    kind: str
    url: Optional[str] = None


class SearchResult(BaseModel):
    contract_version: str = Field(default=SEARCH_CONTRACT_VERSION, alias="contractVersion")
    id: str
    type: SearchResultType
    title: str
    subtitle: str = ""
    summary: Optional[str] = None
    target: SearchTarget
    primary_action: str = Field(alias="primaryAction")
    viewer_capabilities: dict[str, Any] = Field(default_factory=dict, alias="viewerCapabilities")
    web_path: str = Field(alias="webPath")
    source: str = "backend"
    privacy: Optional[dict[str, Any]] = None
    stats: list[SearchStat] = Field(default_factory=list)
    image: Optional[SearchImage] = None
    score: float = 0
    matched_fields: list[str] = Field(default_factory=list, alias="matchedFields")
    scan_state: Optional[str] = Field(default=None, alias="scanState")
    scan_targets: list[dict[str, Any]] = Field(default_factory=list, alias="scanTargets")
    metadata: dict[str, Any] = Field(default_factory=dict)

    model_config = {"populate_by_name": True, "by_alias": True}


class SearchSuggestionSection(BaseModel):
    id: str
    title: str
    results: list[SearchResult] = Field(default_factory=list)

    model_config = {"populate_by_name": True, "by_alias": True}


def normalize_search_query(value: Any) -> str:
    return " ".join(str(value or "").strip().split())


def normalize_search_type(value: Any) -> SearchType:
    normalized = str(value or SearchType.all.value).strip().lower()
    try:
        return SearchType(normalized)
    except ValueError:
        return SearchType.all


def classify_protocol_search(value: str) -> Optional[tuple[LinkTargetType, str]]:
    query = normalize_search_query(value)
    if not query:
        return None

    route_match = re.match(
        r"^/?(?:scan/)?(?P<head>tx|transaction|transactions|account|accounts|proof|proofs)/(?P<id>[1-9A-HJ-NP-Za-km-z]{32,90})/?$",
        query,
        re.IGNORECASE,
    )
    if route_match:
        head = route_match.group("head").lower()
        target_id = route_match.group("id")
        if head in {"tx", "transaction", "transactions"}:
            return LinkTargetType.scan_tx, target_id
        if head in {"account", "accounts"}:
            return LinkTargetType.scan_account, target_id
        return LinkTargetType.proof, target_id

    prefixed_match = re.match(
        r"^(?:tx|transaction|signature|sig|account|acct|address|wallet|proof)\s*[:#/\- ]\s*(?P<id>[1-9A-HJ-NP-Za-km-z]{32,90})$",
        query,
        re.IGNORECASE,
    )
    if prefixed_match:
        lower = query.lower()
        target_id = prefixed_match.group("id")
        if lower.startswith(("tx", "transaction", "signature", "sig")):
            return LinkTargetType.scan_tx, target_id
        if lower.startswith("proof"):
            return LinkTargetType.proof, target_id
        return LinkTargetType.scan_account, target_id

    if not BASE58_RE.match(query):
        return None
    if len(query) > 44:
        return LinkTargetType.scan_tx, query
    if 32 <= len(query) <= 44 and not USERNAME_RE.match(query):
        return LinkTargetType.scan_account, query
    return None


def build_search_result(
    *,
    result_id: str,
    result_type: SearchResultType,
    title: str,
    subtitle: str,
    target_type: LinkTargetType,
    target_id: str,
    source: str = "backend",
    privacy: Optional[dict[str, Any]] = None,
    stats: Optional[list[dict[str, Any]]] = None,
    image: Optional[dict[str, Any]] = None,
    score: float = 0,
    matched_fields: Optional[list[str]] = None,
    scan_state: Optional[str] = None,
    scan_targets: Optional[list[dict[str, Any]]] = None,
    metadata: Optional[dict[str, Any]] = None,
    summary: Optional[str] = None,
) -> dict[str, Any]:
    result = SearchResult(
        id=result_id,
        type=result_type,
        title=title,
        subtitle=subtitle,
        summary=summary,
        target=SearchTarget(**target_ref_dict(target_type.value, target_id, source="search.result")),
        primaryAction=primary_action_for_target(target_type.value).value,
        viewerCapabilities=capabilities_for_target(
            target_type.value,
            can_view=True,
            authenticated=True,
            can_share=True,
            has_scan_target=bool(scan_targets),
        ),
        webPath=canonical_web_path(target_type, target_id),
        source=source,
        privacy=privacy,
        stats=[SearchStat(**stat) for stat in (stats or [])],
        image=SearchImage(**image) if image else None,
        score=score,
        matchedFields=matched_fields or [],
        scanState=scan_state,
        scanTargets=scan_targets or [],
        metadata=metadata or {},
    )
    return result.model_dump(by_alias=True)


def build_search_response(
    *,
    query: str,
    search_type: SearchType,
    results: list[dict[str, Any]],
    limit: int,
) -> dict[str, Any]:
    normalized_query = normalize_search_query(query)
    limited = results[:limit]
    return {
        "contractVersion": SEARCH_CONTRACT_VERSION,
        "query": query,
        "normalizedQuery": normalized_query,
        "type": search_type.value,
        "results": limited,
        "hasMore": len(results) > limit,
    }


def build_search_suggestions_response(
    *,
    sections: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "contractVersion": SEARCH_CONTRACT_VERSION,
        "sections": [
            SearchSuggestionSection(**section).model_dump(by_alias=True)
            for section in sections
            if section.get("results")
        ],
    }


def search_schema() -> dict[str, Any]:
    return {
        "contractVersion": SEARCH_CONTRACT_VERSION,
        "types": [value.value for value in SearchType],
        "resultTypes": [value.value for value in SearchResultType],
        "targetContractVersion": "link.v1",
        "capabilities": [
            "suggestions",
            "recent_searches_client",
            "social_rank_boosts",
            "place_aware_climb_regions",
            "scan_target_previews",
        ],
        "targets": [
            "rider",
            "ride",
            "climb",
            "record_board",
            "local_legend",
            "proof",
            "scan_tx",
            "scan_account",
            "report",
        ],
    }
