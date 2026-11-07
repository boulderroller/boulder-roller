from __future__ import annotations

from ..services.privacy_logging import scrub_log_text
import asyncio
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query, Request

from ..avatar_media_contracts import with_signed_avatar_url
from ..dependencies import AuthenticatedUser, get_optional_current_user, get_repository
from ..link_contracts import LinkTargetType
from ..middleware.rate_limiter import rate_limit
from ..repositories import DatabaseRepository
from ..rider_identity_contracts import public_rider_ref_dict, rider_route_identifier
from ..scan_contracts import scan_targets_for_climb, scan_targets_for_profile, scan_targets_for_protocol, scan_targets_for_ride
from ..search_contracts import (
    SearchResultType,
    SearchType,
    build_search_response,
    build_search_result,
    build_search_suggestions_response,
    classify_protocol_search,
    normalize_search_query,
    normalize_search_type,
    search_schema,
)
from ..services.privacy_resolver import resolve_profile_visibility, resolve_ride_visibility


logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


UUIDISH_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.IGNORECASE)


def _query_limit(limit: int, search_type: SearchType) -> int:
    if search_type == SearchType.all:
        return max(8, min(20, math.ceil(limit / 2)))
    return limit


def _first_text(*values: Any, fallback: str = "") -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return fallback


def _strip_extension(value: Any) -> str:
    text = _first_text(value, fallback="Ride")
    return text.rsplit(".", 1)[0] if "." in text else text


async def _public_search_actor(
    user: Optional[dict[str, Any]],
    current_user: Optional[AuthenticatedUser],
) -> Optional[dict[str, Any]]:
    if not user:
        return None
    privacy = await resolve_profile_visibility(user, current_user)
    row = dict(user)
    if not privacy.can_view:
        row["display_name"] = None
        row["avatar_url"] = None
        row["avatar_storage_path"] = None
        row["is_public"] = False
        return row
    return await with_signed_avatar_url(row) or row


def _format_distance(distance_m: Any) -> Optional[str]:
    try:
        meters = float(distance_m)
    except (TypeError, ValueError):
        return None
    if meters <= 0:
        return None
    if meters >= 1000:
        return f"{meters / 1000:.1f} km"
    return f"{round(meters)} m"


def _format_elevation(elevation_m: Any) -> Optional[str]:
    try:
        meters = float(elevation_m)
    except (TypeError, ValueError):
        return None
    if meters <= 0:
        return None
    return f"{round(meters):,} m"


def _format_duration(duration_s: Any) -> Optional[str]:
    try:
        seconds = int(duration_s)
    except (TypeError, ValueError):
        return None
    if seconds <= 0:
        return None
    hours = seconds // 3600
    minutes = (seconds % 3600) // 60
    if hours:
        return f"{hours}h {minutes:02d}m"
    return f"{minutes}m"


def _parse_datetime(value: Any) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    return None


def _date_label(value: Any) -> Optional[str]:
    parsed = _parse_datetime(value)
    if not parsed:
        return None
    return parsed.astimezone(timezone.utc).strftime("%b %-d, %Y")


def _execute_rows(query: Any) -> list[dict[str, Any]]:
    result = query.execute()
    return [dict(row) for row in (getattr(result, "data", None) or [])]


def _dedupe_rows(rows: list[dict[str, Any]], key: str = "id") -> list[dict[str, Any]]:
    seen: set[str] = set()
    unique: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(key)
        if value is None:
            continue
        row_key = str(value)
        if row_key in seen:
            continue
        seen.add(row_key)
        unique.append(row)
    return unique


def _basic_score(query: str, *values: Any, base: float = 10) -> float:
    normalized = query.lower()
    if not normalized:
        return base
    best = 0.0
    for value in values:
        text = str(value or "").lower()
        if not text:
            continue
        if text == normalized:
            best = max(best, 90)
        elif text.startswith(normalized):
            best = max(best, 70)
        elif normalized in text:
            best = max(best, 45)
    return base + best


def _numeric_boost(value: Any, *, divisor: float, maximum: float) -> float:
    try:
        number = float(value or 0)
    except (TypeError, ValueError):
        return 0
    if number <= 0:
        return 0
    return min(maximum, number / divisor)


async def _search_rider_rows(repo: DatabaseRepository, query: str, limit: int) -> list[dict[str, Any]]:
    custom = getattr(repo, "search_riders", None)
    if custom:
        return await custom(query, limit)

    client = getattr(repo, "client", None)
    if client is None:
        return []

    rows: list[dict[str, Any]] = []
    selections = [
        (
            "id, wallet, username, display_name, avatar_url, avatar_storage_path, "
            "is_public, default_ride_visibility, "
            "location, total_rides, total_distance_km, total_elevation_m, moderation_state"
        ),
        (
            "id, wallet, username, display_name, avatar_url, "
            "is_public, location, total_rides, total_elevation_m, moderation_state"
        ),
        "id, wallet, username, display_name, avatar_url, avatar_storage_path, "
        "is_public, moderation_state",
        "id, wallet, username, display_name, is_public",
    ]
    candidates = [
        ("username", f"%{query.lower()}%"),
        ("display_name", f"%{query}%"),
        ("wallet", f"{query}%"),
    ]
    for field, pattern in candidates:
        for selection in selections:
            try:
                rows.extend(
                    _execute_rows(
                        client.from_("users")
                        .select(selection)
                        .ilike(field, pattern)
                        .limit(limit)
                    )
                )
                break
            except Exception as exc:
                logger.debug("[Search] rider query failed for %s with selection %s: %s", field, selection, exc)
    return _dedupe_rows(rows)


async def _search_climb_rows(repo: DatabaseRepository, query: str, limit: int) -> list[dict[str, Any]]:
    custom = getattr(repo, "search_climbs", None)
    if custom:
        return await custom(query, limit)

    client = getattr(repo, "client", None)
    if client is None:
        return []

    rows: list[dict[str, Any]] = []
    climb_selection = (
        "id, name, signature_hex, distance_m, total_vert_m, avg_gradient_pct, "
        "uci_category, region, total_completions"
    )
    for field, pattern in (("name", f"%{query}%"), ("region", f"%{query}%"), ("signature_hex", f"{query}%")):
        try:
            rows.extend(
                _execute_rows(
                    client.from_("climb_vault")
                    .select(climb_selection)
                    .eq("active", True)
                    .ilike(field, pattern)
                    .limit(limit)
                )
            )
        except Exception as exc:
            logger.debug("[Search] climb_vault query failed for %s: %s", field, exc)

    if UUIDISH_RE.match(query):
        try:
            rows.extend(
                _execute_rows(
                    client.from_("climb_vault")
                    .select(climb_selection)
                    .eq("active", True)
                    .eq("id", query)
                    .limit(1)
                )
            )
        except Exception as exc:
            logger.debug("[Search] climb_vault id query failed: %s", exc)

    if query.isdigit():
        indexed_selection = "id, name, signature_hex, distance_m, vert_m, avg_gradient_pct, total_completions"
        try:
            rows.extend(
                {
                    **row,
                    "source_table": "indexed_vaults",
                    "vault_id": row.get("id"),
                    "total_vert_m": row.get("vert_m"),
                }
                for row in _execute_rows(
                    client.from_("indexed_vaults")
                    .select(indexed_selection)
                    .eq("id", int(query))
                    .limit(1)
                )
            )
        except Exception as exc:
            logger.debug("[Search] indexed_vaults id query failed: %s", exc)

    signature_hexes = [
        str(row["signature_hex"])
        for row in rows
        if row.get("signature_hex") and row.get("vault_id") is None
    ]
    if signature_hexes:
        try:
            indexed_rows = _execute_rows(
                client.from_("indexed_vaults")
                .select("id, signature_hex, total_completions")
                .in_("signature_hex", list(dict.fromkeys(signature_hexes)))
            )
            indexed_by_signature = {
                str(row["signature_hex"]): row
                for row in indexed_rows
                if row.get("signature_hex") and row.get("id") is not None
            }
            for row in rows:
                indexed = indexed_by_signature.get(str(row.get("signature_hex") or ""))
                if indexed and row.get("vault_id") is None:
                    row["vault_id"] = indexed.get("id")
                    row.setdefault("total_completions", indexed.get("total_completions"))
        except Exception as exc:
            logger.debug("[Search] indexed_vaults signature enrichment failed: %s", exc)

    return _dedupe_rows(rows)


async def _search_ride_rows(repo: DatabaseRepository, query: str, limit: int, current_user: Optional[AuthenticatedUser]) -> list[dict[str, Any]]:
    custom = getattr(repo, "search_rides", None)
    if custom:
        return await custom(query, limit, current_user)

    client = getattr(repo, "client", None)
    if client is None:
        return []

    rows: list[dict[str, Any]] = []
    selection = (
        "id, user_id, file_name, started_at, created_at, distance_m, elevation_gain_m, duration_sec, training_metrics, "
        "processing_status, visibility, comments_enabled, moderation_state, ride_hash_hex, "
        "attestation_commitment_hex, ride_attestation_pda, ride_attestation_tx_signature, "
        "ride_attested_at, finalized_at"
    )

    if UUIDISH_RE.match(query):
        try:
            rows.extend(_execute_rows(client.from_("rides").select(selection).eq("id", query).limit(1)))
        except Exception as exc:
            logger.debug("[Search] ride id query failed: %s", exc)

    try:
        rows.extend(
            _execute_rows(
                client.from_("rides")
                .select(selection)
                .ilike("file_name", f"%{query}%")
                .order("started_at", desc=True)
                .limit(limit)
            )
        )
    except Exception as exc:
        logger.debug("[Search] ride file_name query failed: %s", scrub_log_text(exc))

    if current_user:
        try:
            rows.extend(
                _execute_rows(
                    client.from_("rides")
                    .select(selection)
                    .eq("user_id", current_user.user_id)
                    .order("started_at", desc=True)
                    .limit(min(limit, 10))
                )
            )
        except Exception as exc:
            logger.debug("[Search] owner ride query failed: %s", exc)

    return _dedupe_rows(rows)


async def _suggest_climb_rows(repo: DatabaseRepository, limit: int) -> list[dict[str, Any]]:
    custom = getattr(repo, "suggest_climbs", None)
    if custom:
        return await custom(limit)

    client = getattr(repo, "client", None)
    if client is None:
        return []

    climb_selection = (
        "id, name, signature_hex, distance_m, total_vert_m, avg_gradient_pct, "
        "uci_category, region, total_completions"
    )
    try:
        return _execute_rows(
            client.from_("climb_vault")
            .select(climb_selection)
            .eq("active", True)
            .order("total_completions", desc=True)
            .limit(limit)
        )
    except Exception as exc:
        logger.debug("[Search] popular climb suggestions failed: %s", exc)
        return []


async def _suggest_own_ride_rows(
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
    limit: int,
) -> list[dict[str, Any]]:
    if not current_user:
        return []
    custom = getattr(repo, "suggest_own_rides", None)
    if custom:
        return await custom(current_user.user_id, limit)

    list_rides = getattr(repo, "list_rides_for_user", None)
    if not list_rides:
        return []
    try:
        return [dict(row) for row in await list_rides(current_user.user_id)][:limit]
    except Exception as exc:
        logger.debug("[Search] own ride suggestions failed: %s", exc)
        return []


async def _suggest_following_ride_rows(
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
    limit: int,
) -> list[dict[str, Any]]:
    if not current_user:
        return []
    custom = getattr(repo, "suggest_following_rides", None)
    if custom:
        return await custom(current_user.user_id, limit)

    get_following_ids = getattr(repo, "get_following_ids", None)
    get_feed_rides = getattr(repo, "get_feed_rides", None)
    if not get_following_ids or not get_feed_rides:
        return []
    try:
        following_ids = await get_following_ids(current_user.user_id)
        return [dict(row) for row in await get_feed_rides(following_ids, limit=limit)] if following_ids else []
    except Exception as exc:
        logger.debug("[Search] following ride suggestions failed: %s", exc)
        return []


async def _suggest_global_ride_rows(repo: DatabaseRepository, limit: int) -> list[dict[str, Any]]:
    custom = getattr(repo, "suggest_global_rides", None)
    if custom:
        return await custom(limit)

    get_global_rides = getattr(repo, "get_global_rides", None)
    if not get_global_rides:
        return []
    try:
        return [dict(row) for row in await get_global_rides(limit=limit)]
    except Exception as exc:
        logger.debug("[Search] global ride suggestions failed: %s", exc)
        return []


async def _suggest_following_rider_rows(
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
    limit: int,
) -> list[dict[str, Any]]:
    if not current_user:
        return []
    custom = getattr(repo, "suggest_following_riders", None)
    if custom:
        return await custom(current_user.user_id, limit)

    get_following = getattr(repo, "get_following", None)
    if not get_following:
        return []
    try:
        return [dict(row) for row in await get_following(current_user.user_id, limit=limit, offset=0)]
    except Exception as exc:
        logger.debug("[Search] following rider suggestions failed: %s", exc)
        return []


def _rider_identifier(row: dict[str, Any]) -> str:
    return rider_route_identifier(row) or _first_text(row.get("wallet"), fallback="unknown")


async def _build_rider_results(
    rows: list[dict[str, Any]],
    query: str,
    current_user: Optional[AuthenticatedUser],
    repo: Optional[DatabaseRepository] = None,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for raw_row in rows:
        row = await with_signed_avatar_url(raw_row) or raw_row
        privacy = await resolve_profile_visibility(row, current_user, repo=repo)
        if not privacy.can_view:
            continue
        rider_ref = public_rider_ref_dict(
            row,
            viewer_relationship="self" if current_user and str(row.get("id")) == str(current_user.user_id) else None,
        )
        display = _first_text(row.get("display_name"), row.get("username"), fallback="Rider")
        identifier = _rider_identifier(row)
        subtitle_parts = ["Rider"]
        if row.get("username"):
            subtitle_parts.append(f"@{row['username']}")
        if row.get("location"):
            subtitle_parts.append(str(row["location"]))
        stats = []
        if row.get("total_rides") is not None:
            stats.append({"label": "Rides", "value": str(row.get("total_rides") or 0)})
        if row.get("total_elevation_m") is not None:
            stats.append({"label": "Climbing", "value": _format_elevation(row.get("total_elevation_m")) or "0 m"})
        scan_state, scan_targets = scan_targets_for_profile(row)
        is_self = bool(current_user and str(row.get("id")) == str(current_user.user_id))
        is_following = bool(privacy.is_follower)
        rank_reason = "your_profile" if is_self else "following" if is_following else "public_profile"
        rider_ref["viewerRelationship"] = "self" if is_self else "following" if is_following else "none"
        score = _basic_score(query, row.get("username"), row.get("display_name"), row.get("wallet"), base=20)
        if is_self:
            score += 25
        elif is_following:
            score += 18
        score += _numeric_boost(row.get("total_rides"), divisor=5, maximum=12)
        results.append(
            build_search_result(
                result_id=f"rider:{identifier}",
                result_type=SearchResultType.rider,
                title=display,
                subtitle=" · ".join(subtitle_parts),
                target_type=LinkTargetType.rider,
                target_id=identifier,
                privacy=privacy.to_client_dict(),
                stats=stats,
                image={"kind": "avatar", "url": row.get("avatar_url")} if row.get("avatar_url") else {"kind": "avatar"},
                score=score,
                matched_fields=["username", "displayName", "wallet"],
                scan_state=scan_state.value,
                scan_targets=scan_targets,
                summary="You" if is_self else "Following" if is_following else None,
                metadata={
                    "rider": rider_ref,
                    "userId": str(row.get("id")) if row.get("id") else None,
                    "isSelf": is_self,
                    "isFollowing": is_following,
                    "rankReason": rank_reason,
                },
            )
        )
    return results


def _climb_id(row: dict[str, Any]) -> str:
    return str(row.get("vault_id") or row.get("id"))


def _climb_vert(row: dict[str, Any]) -> Any:
    return row.get("total_vert_m") if row.get("total_vert_m") is not None else row.get("vert_m")


def _build_climb_results(rows: list[dict[str, Any]], query: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for row in rows:
        climb_id = _climb_id(row)
        name = _first_text(row.get("name"), fallback=f"Climb {climb_id}")
        stats = []
        distance = _format_distance(row.get("distance_m"))
        vert = _format_elevation(_climb_vert(row))
        gradient = row.get("avg_gradient_pct")
        if distance:
            stats.append({"label": "Distance", "value": distance})
        if vert:
            stats.append({"label": "Climbing", "value": vert})
        if gradient is not None:
            try:
                stats.append({"label": "Grade", "value": f"{float(gradient):.1f}%"})
            except (TypeError, ValueError):
                pass
        subtitle_parts = ["Climb"]
        if row.get("region"):
            subtitle_parts.append(str(row["region"]))
        from ..services.climb_read_metrics import climb_category
        category = climb_category(row.get("distance_m") or row.get("length_m"), row.get("avg_gradient_pct"))
        if category:
            subtitle_parts.append(f"Cat {category}")
        scan_state, scan_targets = scan_targets_for_climb(row)
        region = str(row.get("region") or "")
        is_place_match = bool(query and region and query.lower() in region.lower())
        completions = row.get("total_completions")
        score = _basic_score(query, name, region, row.get("signature_hex"), climb_id, base=30)
        if is_place_match:
            score += 15
        score += _numeric_boost(completions, divisor=2, maximum=18)
        results.append(
            build_search_result(
                result_id=f"climb:{climb_id}",
                result_type=SearchResultType.climb,
                title=name,
                subtitle=" · ".join(subtitle_parts),
                target_type=LinkTargetType.climb,
                target_id=climb_id,
                stats=stats,
                score=score,
                matched_fields=["name", "region", "signature", "id"],
                scan_state=scan_state.value,
                scan_targets=scan_targets,
                summary="Place match" if is_place_match else "Popular climb" if completions else None,
                metadata={
                    "climbId": climb_id,
                    "vaultId": row.get("vault_id"),
                    "vaultSignature": row.get("signature_hex"),
                    "totalCompletions": completions,
                    "placeHint": region if is_place_match else None,
                    "rankReason": "place_match" if is_place_match else "popular_climb" if completions else "text_match",
                },
            )
        )
    return results


async def _build_ride_results(
    rows: list[dict[str, Any]],
    query: str,
    current_user: Optional[AuthenticatedUser],
    repo: DatabaseRepository,
) -> list[dict[str, Any]]:
    user_ids = list({str(row.get("user_id")) for row in rows if row.get("user_id")})
    users_by_id: dict[str, dict[str, Any]] = {}
    if user_ids:
        try:
            users = await repo.get_users_by_ids(user_ids)
            users_by_id = {str(user["id"]): user for user in users if user.get("id")}
        except Exception as exc:
            logger.debug("[Search] ride owner lookup failed: %s", exc)

    visible: list[tuple[dict[str, Any], dict[str, Any], Optional[dict[str, Any]]]] = []
    for row in rows:
        owner = users_by_id.get(str(row.get("user_id")))
        privacy = await resolve_ride_visibility(row, current_user, repo=repo, owner_profile=owner)
        if privacy.can_view:
            visible.append((row, privacy.to_client_dict(), owner))

    summaries = {}
    get_summaries = getattr(repo, "get_interaction_summaries", None)
    if get_summaries:
        try:
            summaries = await get_summaries(
                "ride",
                [str(row.get("id")) for row, _privacy, _owner in visible if row.get("id")],
                current_user.user_id if current_user else None,
            )
        except Exception as exc:
            logger.debug("[Search] ride interaction lookup failed: %s", exc)

    results: list[dict[str, Any]] = []
    following_owner_ids: set[str] = set()
    if current_user:
        get_following_ids = getattr(repo, "get_following_ids", None)
        if get_following_ids:
            try:
                following_owner_ids = {str(owner_id) for owner_id in await get_following_ids(current_user.user_id)}
            except Exception as exc:
                logger.debug("[Search] ride owner follow lookup failed: %s", exc)

    for row, privacy, owner in visible:
        from ..services.training_metrics import project_training
        row = project_training(row, owner=privacy.get("isOwner") is True)
        owner = await _public_search_actor(owner, current_user)
        ride_id = str(row.get("id"))
        title = _strip_extension(row.get("file_name"))
        display_name = _first_text((owner or {}).get("display_name"), (owner or {}).get("username"), fallback="Rider")
        owner_ref = public_rider_ref_dict(owner, fallback_id=row.get("user_id")) if owner or row.get("user_id") else None
        date = _date_label(row.get("started_at") or row.get("created_at"))
        stats = []
        for label, value in (
            ("Distance", _format_distance(row.get("distance_m"))),
            ("Climbing", _format_elevation(row.get("elevation_gain_m"))),
            ("Time", _format_duration(row.get("duration_sec"))),
        ):
            if value:
                stats.append({"label": label, "value": value})
        interactions = summaries.get(ride_id, {}) if isinstance(summaries, dict) else {}
        if interactions.get("kudosCount") is not None:
            stats.append({"label": "Kudos", "value": str(interactions.get("kudosCount") or 0)})
        if interactions.get("commentCount") is not None:
            stats.append({"label": "Comments", "value": str(interactions.get("commentCount") or 0)})
        scan_state, scan_targets = scan_targets_for_ride(row, can_view=True)
        is_owner = bool(current_user and str(row.get("user_id")) == str(current_user.user_id))
        is_following_owner = bool(row.get("user_id") and str(row.get("user_id")) in following_owner_ids)
        score = _basic_score(query, title, ride_id, display_name, base=15)
        if is_owner:
            score += 25
        elif is_following_owner:
            score += 16
        score += _numeric_boost(row.get("elevation_gain_m"), divisor=250, maximum=12)
        results.append(
            build_search_result(
                result_id=f"ride:{ride_id}",
                result_type=SearchResultType.ride,
                title=title,
                subtitle=" · ".join(part for part in ["Ride", display_name, date] if part),
                target_type=LinkTargetType.ride,
                target_id=ride_id,
                privacy=privacy,
                stats=stats,
                score=score,
                matched_fields=["title", "id", "rider"],
                scan_state=scan_state.value,
                scan_targets=scan_targets,
                summary="Your ride" if is_owner else "From a rider you follow" if is_following_owner else None,
                metadata={
                    "rideId": ride_id,
                    "ownerId": row.get("user_id"),
                    "owner": owner_ref,
                    "status": row.get("processing_status"),
                    "visibility": privacy.get("visibility"),
                    "isOwner": is_owner,
                    "isFollowingOwner": is_following_owner,
                    "rankReason": "your_ride" if is_owner else "following" if is_following_owner else "text_match",
                    "kudosCount": interactions.get("kudosCount", 0),
                    "commentCount": interactions.get("commentCount", 0),
                    "viewerHasKudos": interactions.get("viewerHasKudos", False),
                },
            )
        )
    return results


def _build_protocol_result(query: str) -> Optional[dict[str, Any]]:
    classified = classify_protocol_search(query)
    if not classified:
        return None
    target_type, target_id = classified
    scan_state, scan_targets = scan_targets_for_protocol(target_type.value, target_id)
    if target_type == LinkTargetType.scan_tx:
        title = "BoulderScan transaction"
        subtitle = "Protocol transaction"
    elif target_type == LinkTargetType.scan_account:
        title = "BoulderScan account"
        subtitle = "Protocol account"
    else:
        title = "Boulder Roller proof"
        subtitle = "Protocol proof"
    return build_search_result(
        result_id=f"{target_type.value}:{target_id}",
        result_type=SearchResultType.proof,
        title=title,
        subtitle=subtitle,
        target_type=target_type,
        target_id=target_id,
        source="indexer",
        score=100,
        matched_fields=["id"],
        scan_state=scan_state.value,
        scan_targets=scan_targets,
        metadata={"protocolPublic": True},
    )


def _section(section_id: str, title: str, results: list[dict[str, Any]], limit: int) -> Optional[dict[str, Any]]:
    if not results:
        return None
    return {"id": section_id, "title": title, "results": results[:limit]}


@router.get("/schema")
async def get_search_schema() -> dict[str, Any]:
    return search_schema()


@router.get("/suggestions")
@rate_limit(category="search")
async def search_suggestions(
    request: Request,
    limit: int = Query(4, ge=1, le=12),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    sections: list[dict[str, Any]] = []

    if current_user:
        own_rides, following_rides, following_riders = await asyncio.gather(
            _suggest_own_ride_rows(repo, current_user, limit),
            _suggest_following_ride_rows(repo, current_user, limit),
            _suggest_following_rider_rows(repo, current_user, limit),
        )
        own_ride_results = await _build_ride_results(own_rides, "", current_user, repo)
        own_section = _section("your_recent_rides", "Your recent rides", own_ride_results, limit)
        if own_section:
            sections.append(own_section)

        following_ride_results = await _build_ride_results(following_rides, "", current_user, repo)
        following_ride_section = _section("following_rides", "Following rides", following_ride_results, limit)
        if following_ride_section:
            sections.append(following_ride_section)

        following_rider_results = await _build_rider_results(following_riders, "", current_user, repo)
        following_rider_section = _section("following_riders", "Riders you follow", following_rider_results, limit)
        if following_rider_section:
            sections.append(following_rider_section)
    else:
        global_rides = await _suggest_global_ride_rows(repo, limit)
        global_ride_results = await _build_ride_results(global_rides, "", current_user, repo)
        global_ride_section = _section("recent_public_rides", "Recent public rides", global_ride_results, limit)
        if global_ride_section:
            sections.append(global_ride_section)

    popular_climbs = await _suggest_climb_rows(repo, limit)
    popular_climb_section = _section("popular_climbs", "Popular climbs", _build_climb_results(popular_climbs, ""), limit)
    if popular_climb_section:
        sections.append(popular_climb_section)

    return build_search_suggestions_response(sections=sections)


@router.get("")
@rate_limit(category="search")
async def search_app(
    request: Request,
    q: str = Query("", description="Search riders, rides, climbs, and proof targets"),
    result_type: str = Query(
        "all",
        alias="type",
        description="Search type: all, riders, rides, climbs, proofs",
    ),
    limit: int = Query(20, ge=1, le=50),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    normalized_query = normalize_search_query(q)
    search_type = normalize_search_type(result_type)
    if not normalized_query:
        return build_search_response(query=q, search_type=search_type, results=[], limit=limit)

    per_type_limit = _query_limit(limit, search_type)
    results: list[dict[str, Any]] = []
    protocol_result = _build_protocol_result(normalized_query)
    if protocol_result and search_type in {SearchType.all, SearchType.proofs}:
        results.append(protocol_result)

    tasks: list[tuple[str, asyncio.Task[list[dict[str, Any]]]]] = []
    if search_type in {SearchType.all, SearchType.riders}:
        tasks.append(("riders", asyncio.create_task(_search_rider_rows(repo, normalized_query, per_type_limit))))
    if search_type in {SearchType.all, SearchType.climbs}:
        tasks.append(("climbs", asyncio.create_task(_search_climb_rows(repo, normalized_query, per_type_limit))))
    if search_type in {SearchType.all, SearchType.rides}:
        tasks.append(("rides", asyncio.create_task(_search_ride_rows(repo, normalized_query, per_type_limit, current_user))))

    for branch, task in tasks:
        try:
            rows = await task
        except Exception as exc:
            logger.warning("[Search] %s branch failed for query %r: %s", branch, normalized_query, exc)
            continue
        if branch == "riders":
            results.extend(await _build_rider_results(rows, normalized_query, current_user, repo))
        elif branch == "climbs":
            results.extend(_build_climb_results(rows, normalized_query))
        elif branch == "rides":
            results.extend(await _build_ride_results(rows, normalized_query, current_user, repo))

    deduped = list({result["id"]: result for result in results}.values())
    deduped.sort(key=lambda result: result.get("score", 0), reverse=True)
    return build_search_response(query=q, search_type=search_type, results=deduped, limit=limit)
