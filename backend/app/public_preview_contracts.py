"""Public preview contracts for app-domain object links.

Public previews are abridged app objects for signed-out viewers. They should
feel like the app, but they must not depend on private ride telemetry, private
ride history, or wallet/profile identity that is not already public.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import PurePosixPath
from urllib.parse import quote
from typing import Any, Optional

from .rider_identity_contracts import public_rider_ref_dict


PUBLIC_PREVIEW_CONTRACT_VERSION = "public_preview.v1"
PUBLIC_PREVIEW_CACHE_TTL_SECONDS = 0
PUBLIC_PREVIEW_RECORD_BOARD_LIMIT = 10
PUBLIC_PREVIEW_MEDIA_LIMIT = 1

PUBLIC_PREVIEW_FIXTURE_TEXT_RE = re.compile(
    r"("
    r"\bfull\s+stack\s+smoke\b"
    r"|\bsmoke\s+climb\b"
    r"|\bwallet\s+smoke\b"
    r"|\bdevnet\s+economics\s+smoke\b"
    r"|\btest\s+(ride|climb|activity|route|segment)\b"
    r"|\bfixture\b"
    r"|\be2e\b"
    r"|\bintegration\s+test\b"
    r")",
    re.IGNORECASE,
)
PUBLIC_PREVIEW_MEDIA_ALLOWED_STATES = {"visible", "approved", "featured"}

PUBLIC_PREVIEW_SENSITIVE_KEYS = {
    "email",
    "email_address",
    "emailAddress",
    "owner_wallet",
    "ownerWallet",
    "user_wallet",
    "userWallet",
    "wallet",
}


def public_preview_cache_control() -> str:
    # Ride visibility and route masking can change after publication. A shared
    # cache could keep serving the former audience or geometry after that edit.
    return "private, no-store, max-age=0"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clean_text(value: Any, fallback: str) -> str:
    text = str(value or "").strip()
    return text or fallback


def _file_title(row: dict[str, Any], fallback: str = "Ride") -> str:
    raw = row.get("title") or row.get("name") or row.get("file_name") or row.get("fileName")
    title = _clean_text(raw, fallback)
    if "." in title:
        title = title.rsplit(".", 1)[0]
    return _clean_text(title, fallback)


def is_public_preview_fixture_like(*values: Any) -> bool:
    """Return true when a public object name looks like internal smoke/test data."""
    for value in values:
        text = str(value or "").strip()
        if text and PUBLIC_PREVIEW_FIXTURE_TEXT_RE.search(text):
            return True
    return False


def _json_value(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json", by_alias=True)
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_json_value(item) for item in value]
    return value


def strip_sensitive_public_preview_fields(value: Any) -> Any:
    if isinstance(value, list):
        return [strip_sensitive_public_preview_fields(item) for item in value]
    if not isinstance(value, dict):
        return value
    return {
        key: strip_sensitive_public_preview_fields(item)
        for key, item in value.items()
        if key not in PUBLIC_PREVIEW_SENSITIVE_KEYS
    }


def _path(*parts: Any) -> str:
    safe_parts = [str(part).strip("/") for part in parts if str(part or "").strip("/")]
    return "/" + str(PurePosixPath(*safe_parts)) if safe_parts else "/"


def public_preview_policy(
    object_type: str,
    *,
    privacy: Optional[dict[str, Any]] = None,
    login_required_for: Optional[list[str]] = None,
) -> dict[str, Any]:
    return {
        "mode": "public_preview",
        "objectType": object_type,
        "rawGpsAvailable": False,
        "streamsAvailable": False,
        "tilesAvailable": False,
        "privateRideHistoryAvailable": False,
        "unreviewedProjectionsAvailable": False,
        "walletRequired": False,
        "loginRequiredFor": login_required_for or ["full_detail", "upload_ride"],
        "blockedSurfaces": ["raw_gps", "streams", "tiles", "private_ride_history"],
        "privacy": privacy,
    }


def _public_preview_image_url(canonical_path: str) -> str:
    """Static share-image function with the object as query parameters (see web/portal/api/og.ts)."""
    parts = [part for part in canonical_path.split("/") if part]
    if len(parts) != 2:
        return "https://app.boulderroller.xyz/api/og"
    return "https://app.boulderroller.xyz/api/og?kind=" + parts[0] + "&id=" + quote(parts[1], safe="")


def public_preview_seo(
    *,
    title: str,
    description: str,
    canonical_path: str,
    object_type: str,
    robots: str = "index,follow",
    image_alt: Optional[str] = None,
) -> dict[str, Any]:
    return {
        "title": title,
        "description": description,
        "canonicalPath": canonical_path,
        "robots": robots,
        "openGraph": {
            "type": object_type,
            "image": {
                "kind": "public_preview_card",
                "url": _public_preview_image_url(canonical_path),
                "alt": image_alt or title,
            },
        },
    }


def public_preview_assets(
    *,
    object_type: str,
    route_preview: Optional[dict[str, Any]] = None,
    record_board: Optional[dict[str, Any]] = None,
    media: Optional[list[dict[str, Any]]] = None,
    alt: Optional[str] = None,
) -> dict[str, Any]:
    assets: dict[str, Any] = {
        "contractVersion": PUBLIC_PREVIEW_CONTRACT_VERSION,
        "objectType": object_type,
        "openGraphImage": {
            "kind": "public_preview_card",
            "status": "available",
            "alt": alt,
        },
    }
    if route_preview is not None:
        fallback_reason = route_preview.get("fallbackReason")
        assets["routePreview"] = {
            "kind": (
                "route_unavailable_preview"
                if fallback_reason == "route_unavailable"
                else "redacted_route_preview"
                if route_preview.get("privacy", {}).get("redactedGps")
                else "route_preview"
            ),
            "preview": route_preview,
        }
    if record_board is not None:
        assets["recordBoard"] = {
            "kind": "record_board_preview",
            "preview": record_board,
        }
    if media:
        assets["media"] = {
            "kind": "ride_media_preview",
            "items": media,
        }
    return assets


def public_route_unavailable_preview(
    *,
    source: str,
    place_label: Optional[str] = None,
    fallback_reason: str = "route_unavailable",
    redacted_gps: bool = False,
) -> dict[str, Any]:
    return {
        "contractVersion": "route_preview.v1",
        "source": source,
        "points": [],
        "segments": [],
        "pointCount": 0,
        "bounds": None,
        "placeLabel": place_label,
        "fallbackReason": fallback_reason,
        "privacy": {
            "redactedGps": redacted_gps,
        },
    }


def public_preview_media_items(
    media: list[dict[str, Any]],
    *,
    limit: int = PUBLIC_PREVIEW_MEDIA_LIMIT,
) -> list[dict[str, Any]]:
    """Keep signed-out media intentional: public preview accepts visible cover assets only."""
    items: list[dict[str, Any]] = []
    for raw_item in media:
        item = _json_value(raw_item)
        if not isinstance(item, dict) or not item.get("url"):
            continue
        state = str(item.get("moderationState") or item.get("moderation_state") or "visible").lower()
        if state not in PUBLIC_PREVIEW_MEDIA_ALLOWED_STATES:
            continue
        if item.get("role") != "cover":
            continue
        items.append(item)
        if len(items) >= limit:
            break
    return items


def build_public_record_board(
    record_board: Optional[Any],
    *,
    limit: int = PUBLIC_PREVIEW_RECORD_BOARD_LIMIT,
) -> Optional[dict[str, Any]]:
    board = _json_value(record_board)
    if not isinstance(board, dict):
        return None

    raw_entries = board.get("entries") or board.get("leaderboard") or []
    entries: list[dict[str, Any]] = []
    for index, raw_entry in enumerate(raw_entries[:limit]):
        entry = _json_value(raw_entry)
        if not isinstance(entry, dict):
            continue
        rank = int(entry.get("rank") or index + 1)
        rider = None
        if not (entry.get("identityHidden") or entry.get("identity_hidden")) and (entry.get("username") or entry.get("displayName") or entry.get("display_name")):
            rider = public_rider_ref_dict(
                entry,
                fallback_id=entry.get("userId") or entry.get("user_id"),
                is_public=True,
            )
        entries.append(
            {
                "rank": rank,
                "position": entry.get("position"),
                "competitionRank": entry.get("competitionRank", entry.get("competition_rank")),
                "tieSize": entry.get("tieSize", entry.get("tie_size")),
                "isTied": entry.get("isTied", entry.get("is_tied")),
                "bestTimeSeconds": entry.get("bestTimeSeconds") or entry.get("best_time_seconds"),
                "avgPowerW": (entry.get("avgPowerW", entry.get("avg_power_w"))
                              if entry.get("powerKind", entry.get("power_kind")) != "estimated" else None),
                "powerKind": entry.get("powerKind", entry.get("power_kind")),
                "estimatedPowerW": entry.get("estimatedPowerW", entry.get("estimated_power_w")),
                "estimatedPowerRangeW": entry.get("estimatedPowerRangeW", entry.get("estimated_power_range_w")),
                **({"wPerKg": entry.get("wPerKg", entry.get("w_per_kg"))}
                   if entry.get("wPerKg", entry.get("w_per_kg")) is not None else {}),
                "completionId": entry.get("completionId") or entry.get("completion_id"),
                **({"effortId": entry.get("effortId") or entry.get("effort_id")}
                   if rider and (entry.get("effortId") or entry.get("effort_id")) else {}),
                **({"rideId": entry.get("rideId") or entry.get("ride_id")}
                   if rider and (entry.get("rideId") or entry.get("ride_id")) else {}),
                "achievedAt": (entry.get("achievedAt") or entry.get("achieved_at")) if rider else None,
                "rider": rider
                or {
                    "displayLabel": f"Rider {rank}",
                    "identityHidden": True,
                },
            }
        )

    return {
        "contractVersion": "record_board_preview.v1",
        "climbId": board.get("climbId") or board.get("climb_id") or board.get("segment_id"),
        "climbName": board.get("climbName") or board.get("climb_name") or board.get("segment_name"),
        "vaultId": board.get("vaultId") or board.get("vault_id"),
        "entries": entries,
        "rowLimit": limit,
        "visibleRows": len(entries),
        "hiddenRows": max(0, len(raw_entries) - len(entries)),
        "identityPolicy": {
            "wallets": "redacted",
            "profileFields": "public_profile_only",
        },
        "truthSource": board.get("truthSource") or board.get("truth_source") or "onchain",
    }


def build_ride_public_preview(
    ride: dict[str, Any],
    *,
    privacy: dict[str, Any],
    owner: Optional[dict[str, Any]] = None,
    route_preview: Optional[dict[str, Any]] = None,
    media: Optional[list[dict[str, Any]]] = None,
    shape: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    ride_id = str(ride.get("id"))
    title = _file_title(ride)
    canonical_path = _path("rides", ride_id)
    media = public_preview_media_items(media or [])
    primary_media = next((item for item in media if item.get("role") == "cover"), media[0] if media else None)
    description = _clean_text(
        ride.get("location") or ride.get("place_label") or ride.get("placeLabel"),
        "Ride preview on Boulder Roller.",
    )
    rider = public_rider_ref_dict(owner, fallback_id=ride.get("user_id")) if owner else None
    threshold_state = ride.get("_threshold_economy_state")
    if threshold_state is None:
        threshold_state = ride.get("threshold_economy_state")
    stored_cal = (
        ride.get("cal_earned")
        if ride.get("cal_earned") is not None
        else ride.get("calEarned")
    )
    if ride.get("reward_policy") == "threshold_provisional_hold_v1":
        cal_earned = (
            ride.get("_threshold_released_cal", stored_cal)
            if threshold_state == "counted"
            else None
        )
    else:
        cal_earned = stored_cal
    preview = {
        "id": ride_id,
        "title": title,
        "status": ride.get("processing_status") or ride.get("status"),
        "startedAt": ride.get("started_at") or ride.get("startedAt"),
        "createdAt": ride.get("created_at") or ride.get("createdAt"),
        "distanceM": ride.get("distance_m") or ride.get("distanceM"),
        "elevationM": ride.get("elevation_gain_m") or ride.get("elevationM"),
        "durationS": ride.get("duration_sec") or ride.get("durationS"),
        "attestationStatus": ride.get("attestation_status") or ride.get("attestationStatus"),
        "rideAttestedAt": ride.get("ride_attested_at") or ride.get("rideAttestedAt"),
        "finalizedAt": ride.get("finalized_at") or ride.get("finalizedAt"),
        "visibility": privacy.get("visibility"),
        "privacy": privacy,
        "rider": rider,
        "routePreview": route_preview,
        "media": media,
        "primaryMedia": primary_media,
    }
    if shape:
        for field in ("elevation_profile", "counted_spans"):
            if field in shape:
                preview[field] = shape[field]
    if privacy.get("isOwner") is True:
        preview["calEarned"] = cal_earned
        preview["dungEarned"] = ride.get("dung_minted") or ride.get("dungEarned")
    if threshold_state in {"held", "counted", "lapsed", "review", "not_counted"}:
        preview["thresholdEconomyState"] = threshold_state
    preview = {key: value for key, value in preview.items() if value is not None}
    return {
        "contractVersion": PUBLIC_PREVIEW_CONTRACT_VERSION,
        "objectType": "ride",
        "id": ride_id,
        "canonicalPath": canonical_path,
        "compatPaths": [_path("activities", ride_id)],
        "title": title,
        "previewPolicy": public_preview_policy("ride", privacy=privacy),
        "seo": public_preview_seo(
            title=f"{title} · Ride · Boulder Roller",
            description=description,
            canonical_path=canonical_path,
            object_type="ride",
            image_alt=title,
        ),
        "assets": public_preview_assets(
            object_type="ride",
            route_preview=route_preview,
            media=media,
            alt=title,
        ),
        "ride": preview,
        "freshness": {
            "source": "backend",
            "loadedAt": utc_now_iso(),
            "cacheTtlSeconds": PUBLIC_PREVIEW_CACHE_TTL_SECONDS,
        },
    }


def build_climb_public_preview(
    climb: Any,
    *,
    record_board: Optional[Any] = None,
) -> dict[str, Any]:
    climb_json = _json_value(climb)
    if not isinstance(climb_json, dict):
        climb_json = {}
    climb_id = str(climb_json.get("id"))
    name = _clean_text(climb_json.get("name"), "Climb")
    canonical_path = _path("climbs", climb_id)
    route_preview = (
        climb_json.get("route_preview")
        or climb_json.get("routePreview")
        or public_route_unavailable_preview(
            source="climb_route_asset",
            place_label=climb_json.get("region"),
        )
    )
    board_preview = build_public_record_board(record_board)
    preview = {
        "id": climb_id,
        "name": name,
        "region": climb_json.get("region"),
        "lengthM": climb_json.get("length_m") or climb_json.get("lengthM"),
        "elevGainM": climb_json.get("elev_gain_m") or climb_json.get("elevGainM"),
        "avgGradientPct": climb_json.get("avg_gradient_pct") or climb_json.get("avgGradientPct"),
        "elevationProfile": climb_json.get("elevation_profile") or climb_json.get("elevationProfile"),
        "geographicData": climb_json.get("geographic_data"),
        "category": climb_json.get("category"),
        "routePreview": route_preview,
        "vaultEconomy": climb_json.get("vault_economy") or climb_json.get("vaultEconomy"),
        "recordBoard": board_preview,
    }
    preview = {key: value for key, value in preview.items() if value is not None}
    description = _clean_text(climb_json.get("region"), "Climb preview on Boulder Roller.")
    return {
        "contractVersion": PUBLIC_PREVIEW_CONTRACT_VERSION,
        "objectType": "climb",
        "id": climb_id,
        "canonicalPath": canonical_path,
        "title": name,
        "previewPolicy": public_preview_policy(
            "climb",
            login_required_for=["my_position", "deposit_cal", "withdraw_cal", "collect_rewards"],
        ),
        "seo": public_preview_seo(
            title=f"{name} · Climb · Boulder Roller",
            description=description,
            canonical_path=canonical_path,
            object_type="climb",
            image_alt=name,
        ),
        "assets": public_preview_assets(
            object_type="climb",
            route_preview=route_preview,
            record_board=board_preview,
            alt=name,
        ),
        "climb": preview,
        "freshness": {
            "source": "backend",
            "loadedAt": utc_now_iso(),
            "cacheTtlSeconds": PUBLIC_PREVIEW_CACHE_TTL_SECONDS,
        },
    }


def build_rider_public_preview(
    profile_payload: dict[str, Any],
    *,
    identifier: str,
) -> dict[str, Any]:
    sanitized = strip_sensitive_public_preview_fields(_json_value(profile_payload))
    rider = sanitized.get("rider") if isinstance(sanitized, dict) else None
    profile = sanitized.get("profile") if isinstance(sanitized, dict) else {}
    privacy = sanitized.get("privacy") if isinstance(sanitized, dict) else None
    display_name = None
    if isinstance(rider, dict):
        display_name = rider.get("displayName") or rider.get("username")
    if not display_name and isinstance(profile, dict):
        display_name = profile.get("display_name") or profile.get("displayName") or profile.get("username")
    title = _clean_text(display_name, "Rider")
    canonical_identifier = str(identifier).lstrip("@")
    canonical_path = _path("riders", canonical_identifier)
    can_view = bool((privacy or {}).get("canView", True))
    is_owner = bool((privacy or {}).get("isOwner", False))
    if not is_owner and isinstance(profile, dict):
        profile.pop("total_dung_earned", None)
        profile.pop("totalDungEarned", None)
    recent_rides = sanitized.get("recentRides") if isinstance(sanitized, dict) else None
    if not is_owner and isinstance(recent_rides, dict):
        for ride in recent_rides.get("rides") or []:
            if isinstance(ride, dict):
                ride.pop("dung_minted", None)
                ride.pop("dungMinted", None)
                ride.pop("cal_earned", None)
                ride.pop("calEarned", None)
    return {
        "contractVersion": PUBLIC_PREVIEW_CONTRACT_VERSION,
        "objectType": "rider",
        "id": (profile or {}).get("id") if isinstance(profile, dict) else None,
        "canonicalPath": canonical_path,
        "title": title,
        "previewPolicy": public_preview_policy(
            "rider",
            privacy=privacy,
            login_required_for=["follow", "full_profile"],
        ),
        "seo": public_preview_seo(
            title=f"{title} · Rider · Boulder Roller",
            description="Rider profile on Boulder Roller.",
            canonical_path=canonical_path,
            object_type="profile",
            robots="index,follow" if can_view else "noindex,nofollow",
            image_alt=title,
        ),
        "assets": public_preview_assets(object_type="rider", alt=title),
        "rider": rider,
        "profile": profile,
        "modules": sanitized.get("modules", []) if isinstance(sanitized, dict) else [],
        "recentRides": recent_rides,
        "beetleCards": sanitized.get("beetleCards") if isinstance(sanitized, dict) else None,
        "leaderboard": sanitized.get("leaderboard") if isinstance(sanitized, dict) else None,
        "viewerCapabilities": sanitized.get("viewerCapabilities") if isinstance(sanitized, dict) else None,
        "freshness": {
            "source": "backend",
            "loadedAt": utc_now_iso(),
            "cacheTtlSeconds": PUBLIC_PREVIEW_CACHE_TTL_SECONDS,
        },
    }
