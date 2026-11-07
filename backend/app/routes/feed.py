from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, status

from ..dependencies import AuthenticatedUser, get_achievement_repository, get_current_user, get_optional_current_user, get_repository
from ..avatar_media_contracts import with_signed_avatar_url
from ..feed_contracts import (
    build_activity_feed_event,
    build_ride_feed_event,
    feed_cursor,
    infer_activity_event_type,
    parse_feed_datetime,
)
from ..ride_media_contracts import serialize_ride_media_list
from ..repositories import DatabaseRepository, create_notification_repository
from ..repositories.achievement import AchievementRepository
from ..repositories.ride import RideRepository
from ..repositories.vault import VaultRepository
from ..services.privacy_resolver import resolve_profile_visibility, resolve_ride_visibility
from ..services.ride_privacy import (
    PrivacySettingsUnavailable,
    RidePrivacyPolicy,
    project_route_points,
)
from ..token_amounts import exact_token_amount

router = APIRouter(tags=["feed"])
logger = logging.getLogger(__name__)


async def _attach_threshold_economy_states(
    rides: list[dict[str, Any]],
    repo: DatabaseRepository,
) -> list[dict[str, Any]]:
    """Batch-project held-ride money state; failures remain fail-closed."""
    held_ids = [
        str(ride.get("id"))
        for ride in rides
        if ride.get("id")
        and ride.get("reward_policy") == "threshold_provisional_hold_v1"
    ]
    if not held_ids:
        return rides
    reader = getattr(repo, "get_reward_threshold_ride_projections", None)
    if not callable(reader):
        client = getattr(repo, "client", None)
        if client is None:
            return rides
        reader = RideRepository(client).get_reward_threshold_ride_projections
    try:
        projections = await reader(held_ids)
    except Exception as exc:
        logger.warning("Threshold feed projection unavailable: %s", exc)
        return rides

    projected: list[dict[str, Any]] = []
    for ride in rides:
        projection = projections.get(str(ride.get("id")))
        if not isinstance(projection, dict):
            projected.append(ride)
            continue
        row = dict(ride)
        row["_threshold_economy_state"] = projection.get("state")
        if projection.get("state") == "counted":
            row["_threshold_released_cal"] = projection.get("cal_earned")
        projected.append(row)
    return projected


def _sort_and_limit_events(events: list[dict], limit: int) -> list[dict]:
    return sorted(
        events,
        key=lambda event: parse_feed_datetime(event.get("occurredAt") or event.get("createdAt"))
        or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )[:limit]


async def _home_social_counts(repo: DatabaseRepository, user_id: str) -> dict[str, int]:
    client = getattr(repo, "client", None)
    if client is not None:
        try:
            followers_response, following_response = await asyncio.gather(
                repo._run(
                    lambda: client.table("follows")
                    .select("follower_id", count="exact", head=True)
                    .eq("following_id", user_id)
                    .execute()
                ),
                repo._run(
                    lambda: client.table("follows")
                    .select("following_id", count="exact", head=True)
                    .eq("follower_id", user_id)
                    .execute()
                ),
            )
            return {
                "followerCount": int(getattr(followers_response, "count", None) or 0),
                "followingCount": int(getattr(following_response, "count", None) or 0),
            }
        except Exception:
            pass

    get_followers = getattr(repo, "get_followers", None)
    get_following = getattr(repo, "get_following", None)
    if not get_followers or not get_following:
        return {"followerCount": 0, "followingCount": 0}
    try:
        followers, following = await asyncio.gather(
            get_followers(user_id, limit=500, offset=0),
            get_following(user_id, limit=500, offset=0),
        )
    except Exception:
        return {"followerCount": 0, "followingCount": 0}
    return {
        "followerCount": len(followers),
        "followingCount": len(following),
    }


async def _home_suggested_riders(
    repo: DatabaseRepository,
    current_user: Optional[AuthenticatedUser],
    limit: int,
) -> list[dict[str, Any]]:
    if not current_user:
        return []

    custom = getattr(repo, "suggest_riders", None)
    if custom:
        return await custom(current_user.user_id, limit)

    client = getattr(repo, "client", None)
    if client is None:
        return []

    get_following_ids = getattr(repo, "get_following_ids", None)
    try:
        following_ids = set(await get_following_ids(current_user.user_id)) if get_following_ids else set()
    except Exception:
        following_ids = set()
    following_ids.add(current_user.user_id)
    try:
        result = await repo._run(
            lambda: client.table("users")
            .select("id, wallet, username, display_name, avatar_url, avatar_storage_path, is_public")
            .neq("id", current_user.user_id)
            .eq("is_public", True)
            .order("created_at", desc=True)
            .limit(limit * 3)
            .execute()
        )
    except Exception:
        return []

    suggestions: list[dict[str, Any]] = []
    for user in getattr(result, "data", None) or []:
        if user.get("id") in following_ids:
            continue
        privacy = await resolve_profile_visibility(user, current_user)
        if not privacy.can_view:
            continue
        user = await with_signed_avatar_url(user) or user
        suggestions.append({
            "id": user.get("id"),
            "wallet": user.get("wallet"),
            "username": user.get("username"),
            "displayName": user.get("display_name"),
            "avatarUrl": user.get("avatar_url"),
        })
        if len(suggestions) >= limit:
            break
    return suggestions


async def _home_popular_climbs(repo: DatabaseRepository, limit: int) -> list[dict[str, Any]]:
    client = getattr(repo, "client", None)
    if client is None:
        return []
    try:
        indexed_result = await repo._run(
            lambda: client.from_("indexed_vaults")
            .select("id, name, signature_hex, vert_m, total_completions")
            .order("total_completions", desc=True)
            .limit(limit)
            .execute()
        )
        indexed_rows = list(getattr(indexed_result, "data", None) or [])
        if indexed_rows:
            totals = await VaultRepository(client).get_vault_stake_totals(
                [int(row["id"]) for row in indexed_rows]
            )
            climbs = []
            for row in indexed_rows:
                vault_id = int(row["id"])
                active_cal = exact_token_amount(
                    totals[vault_id]["total_cal_staked"],
                    field_name="total_cal_staked",
                )
                climbs.append({
                    "id": str(vault_id),
                    "name": row.get("name") or "Climb",
                    "region": None,
                    "elevGainM": float(row.get("vert_m") or 0),
                    "completions": int(row.get("total_completions") or 0),
                    "staked": active_cal.units,
                    "stakedBaseUnits": active_cal.base_units,
                    "vaultSignature": row.get("signature_hex"),
                })
            return climbs

        result = await repo._run(
            lambda: client.from_("climb_vault")
            .select("id, name, region, total_vert_m, total_completions, signature_hex")
            .eq("active", True)
            .order("total_completions", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception:
        return []
    climbs = []
    for row in getattr(result, "data", None) or []:
        climbs.append({
            "id": str(row.get("id")),
            "name": row.get("name") or "Climb",
            "region": row.get("region"),
            "elevGainM": float(row.get("total_vert_m") or 0),
            "completions": int(row.get("total_completions") or 0),
            "staked": "0",
            "stakedBaseUnits": "0",
            "vaultSignature": row.get("signature_hex"),
        })
    return climbs


async def _home_achievements(
    current_user: Optional[AuthenticatedUser],
    achievements_repo: AchievementRepository,
    limit: int,
) -> list[dict[str, Any]]:
    if not current_user:
        return []
    try:
        achievements = await achievements_repo.get_user_achievements(current_user.user_id, limit=limit)
    except Exception:
        return []
    return [dict(item) for item in achievements[:limit]]


async def _home_unread_count(current_user: Optional[AuthenticatedUser]) -> int:
    if not current_user:
        return 0
    try:
        notification_repo = create_notification_repository()
        return int(await notification_repo.get_unread_count(current_user.wallet))
    except Exception:
        return 0


async def _route_preview_points_for_feed(
    ride: dict, privacy: dict, repo: DatabaseRepository
) -> tuple[list[dict], list[dict]] | None:
    """Viewer-projected preview points plus the privacy zones applied (so the
    preview builder keeps simplified edges under the same zone law)."""
    gps_track = ride.get("gps_track")
    if not gps_track:
        return None

    try:
        from ..utils.polyline import decode_gps_track
        points = decode_gps_track(gps_track)
    except Exception:
        return [], []

    if not points or privacy.get("isOwner"):
        return points, []
    try:
        policy = RidePrivacyPolicy.from_values(
            visibility=privacy.get("visibility"),
            map_visibility=privacy.get("mapVisibility"),
            map_hide_start_m=privacy.get("mapHideStartM"),
            map_hide_end_m=privacy.get("mapHideEndM"),
        )
        zones: list[dict[str, Any]] = []
        if policy.map_visibility != "hide_entire":
            response = await repo._run(
                lambda: repo._client.table("privacy_zones")
                .select("latitude,longitude,radius_m")
                .eq("user_id", str(ride.get("user_id") or ride.get("rider_id") or ""))
                .execute()
            )
            zone_rows = getattr(response, "data", None)
            if zone_rows is None:
                raise PrivacySettingsUnavailable("privacy zones unavailable")
            zones = [dict(zone) for zone in zone_rows]
        return project_route_points(points, policy, privacy_zones=zones), zones
    except Exception as exc:
        # A public feed must never recover from privacy storage failure by
        # returning raw coordinates.
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Route privacy is temporarily unavailable. Please retry.",
        ) from exc


async def _feed_media_by_ride(
    repo: DatabaseRepository,
    ride_ids: list[str],
) -> dict[str, list[dict[str, Any]]]:
    unique_ids = [str(ride_id) for ride_id in dict.fromkeys(ride_ids) if ride_id]
    if not unique_ids:
        return {}

    list_many = getattr(repo, "list_ride_media_for_rides", None)
    rows_by_ride: Optional[dict[str, list[dict[str, Any]]]] = None
    if list_many:
        try:
            rows_by_ride = await list_many(unique_ids)
        except Exception:
            rows_by_ride = None
    if rows_by_ride is None:
        list_media = getattr(repo, "list_ride_media", None)
        if not list_media:
            return {}
        try:
            grouped_rows = await asyncio.gather(*(list_media(ride_id) for ride_id in unique_ids))
            rows_by_ride = dict(zip(unique_ids, grouped_rows))
        except Exception:
            rows_by_ride = {}

    async def _serialize_group(ride_id: str, rows: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]]]:
        try:
            media = await serialize_ride_media_list(rows)
        except Exception:
            return ride_id, []
        return ride_id, [
            item.model_dump(by_alias=True, mode="json")
            for item in media
            if item.url
        ]

    groups = await asyncio.gather(*(
        _serialize_group(ride_id, rows_by_ride.get(ride_id, []))
        for ride_id in unique_ids
    ))
    return {ride_id: media for ride_id, media in groups if media}


async def _feed_actor_profile(
    user: dict[str, Any],
    current_user: Optional[AuthenticatedUser],
) -> dict[str, Any]:
    privacy = await resolve_profile_visibility(user, current_user)
    row = dict(user)
    if not privacy.can_view:
        row["display_name"] = None
        row["bio"] = None
        row["avatar_url"] = None
        row["avatar_storage_path"] = None
        row["is_public"] = False
        return row
    return await with_signed_avatar_url(row) or row


async def _feed_users_by_id(
    repo: DatabaseRepository,
    user_ids: list[str],
    current_user: Optional[AuthenticatedUser],
) -> dict[str, dict[str, Any]]:
    unique_ids = [str(user_id) for user_id in dict.fromkeys(user_ids) if user_id]
    if not unique_ids:
        return {}
    users = await repo.get_users_by_ids(unique_ids)
    visible_users = await asyncio.gather(*(
        _feed_actor_profile(user, current_user)
        for user in users
    ))
    return {
        str(user["id"]): user
        for user in visible_users
        if user.get("id")
    }


async def _ride_for_feed_event(
    ride: dict,
    privacy: dict,
    repo: DatabaseRepository,
    media: Optional[list[dict[str, Any]]] = None,
) -> dict:
    from ..services.training_metrics import project_training
    ride = project_training(ride, owner=privacy.get("isOwner") is True)
    projected = await _route_preview_points_for_feed(ride, privacy, repo)
    route_points, route_zones = projected if projected is not None else (None, [])
    if media is None:
        media = []
        list_media = getattr(repo, "list_ride_media", None)
        if list_media and ride.get("id"):
            try:
                serialized = await serialize_ride_media_list(await list_media(str(ride.get("id"))))
                media = [
                    item.model_dump(by_alias=True, mode="json")
                    for item in serialized
                    if item.url
                ]
            except Exception:
                media = []

    if route_points is None and not media:
        return ride

    row = {**ride}
    if route_points is not None:
        row["_route_preview_points"] = route_points
        row["_route_preview_zones"] = route_zones
    if media:
        row["_media"] = media
    return row


@router.get("")
async def get_feed(
    limit: int = Query(20, le=100),
    before: Optional[datetime] = None,
    current_user: AuthenticatedUser = Depends(get_current_user),
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Get activity feed from followed users.
    """
    following = await repo.get_following_ids(current_user.user_id)
    # Home is a social feed, not a replacement for the rider's own timeline.
    # Include self in the same privacy-safe feed query so a just-published ride
    # does not vanish merely because the rider follows nobody yet.
    source_user_ids = list(dict.fromkeys([current_user.user_id, *following]))

    get_followed_rides = getattr(repo, "get_feed_rides", None)
    if get_followed_rides:
        rides = await get_followed_rides(
            user_ids=source_user_ids,
            limit=limit,
            before=before,
        )
        rides = await _attach_threshold_economy_states(rides, repo)

        ride_user_ids = list({r.get("user_id") for r in rides if r.get("user_id")})
        ride_users_by_id = await _feed_users_by_id(repo, ride_user_ids, current_user)

        get_summaries = getattr(repo, "get_interaction_summaries", None)
        visible_rides: list[tuple[dict, dict]] = []
        for ride in rides:
            decision = await resolve_ride_visibility(
                ride,
                current_user,
                repo=repo,
                owner_profile=ride_users_by_id.get(ride.get("user_id")),
            )
            if decision.can_view:
                visible_rides.append((ride, decision.to_client_dict()))

        summaries = await get_summaries(
            "ride",
            [str(ride.get("id")) for ride, _privacy in visible_rides if ride.get("id")],
            current_user.user_id,
        ) if get_summaries else {}
        media_by_ride = await _feed_media_by_ride(
            repo,
            [str(ride.get("id")) for ride, _privacy in visible_rides if ride.get("id")],
        )
        activities = []
        for ride, privacy in visible_rides:
            ride_for_event = await _ride_for_feed_event(
                ride,
                privacy,
                repo,
                media_by_ride.get(str(ride.get("id")), []),
            )
            event = build_ride_feed_event(
                ride_for_event,
                ride_users_by_id.get(ride.get("user_id")),
                summaries.get(str(ride.get("id"))),
                privacy,
            )
            if event:
                activities.append(event)

        get_legacy_activities = getattr(repo, "get_feed_activities", None)
        legacy_activities = []
        if get_legacy_activities:
            legacy_activities = await get_legacy_activities(
                user_ids=source_user_ids,
                limit=limit,
                before=before,
            )
            for activity in legacy_activities:
                user = ride_users_by_id.get(activity.get("user_id"))
                if not user and activity.get("user_id"):
                    users = await _feed_users_by_id(repo, [activity.get("user_id")], current_user)
                    user = users.get(str(activity.get("user_id")))
                activities.append(
                    build_activity_feed_event(
                        activity,
                        user,
                        is_owner=str(activity.get("user_id")) == str(current_user.user_id),
                    )
                )

        activities = _sort_and_limit_events(activities, limit)
        return {
            "contractVersion": "feed.v1",
            "activities": activities,
            "has_more": len(rides) == limit or len(legacy_activities) == limit,
            "next_cursor": feed_cursor(activities),
        }

    activities = await repo.get_feed_activities(
        user_ids=source_user_ids,
        limit=limit,
        before=before,
    )

    # Batch-fetch user profiles to avoid N+1
    user_ids = list({a.get("user_id") for a in activities if a.get("user_id")})
    users_by_id = await _feed_users_by_id(repo, user_ids, current_user)

    enriched = []
    for activity in activities:
        user = users_by_id.get(activity.get("user_id"))
        enriched.append(
            build_activity_feed_event(
                activity,
                user,
                is_owner=str(activity.get("user_id")) == str(current_user.user_id),
            )
        )

    return {
        "contractVersion": "feed.v1",
        "activities": enriched,
        "has_more": len(activities) == limit,
        "next_cursor": feed_cursor(enriched),
    }


@router.get("/global")
async def get_global_feed(
    limit: int = Query(20, le=100),
    before: Optional[datetime] = None,
    activity_type: Optional[str] = None,
    repo: DatabaseRepository = Depends(get_repository),
):
    """
    Global public activity feed.
    Returns recent rides from all users as activity items.
    """
    # Get recent rides from all users
    rides = await repo.get_global_rides(limit=limit, before=before)
    rides = await _attach_threshold_economy_states(rides, repo)
    legacy_activities = []
    get_global_activities = getattr(repo, "get_global_activities", None)
    if get_global_activities:
        legacy_activities = await get_global_activities(
            limit=limit,
            before=before,
            activity_type=activity_type,
        )

    # Batch-fetch user profiles to avoid N+1
    ride_user_ids = list({r.get("user_id") for r in rides if r.get("user_id")})
    ride_users_by_id = await _feed_users_by_id(repo, ride_user_ids, None)

    get_summaries = getattr(repo, "get_interaction_summaries", None)
    summaries = await get_summaries(
        "ride",
        [str(ride.get("id")) for ride in rides if ride.get("id")],
        None,
    ) if get_summaries else {}
    visible_ride_ids: list[str] = []
    visible_decisions: list[tuple[dict, dict]] = []
    for ride in rides:
        decision = await resolve_ride_visibility(
            ride,
            None,
            repo=repo,
            owner_profile=ride_users_by_id.get(ride.get("user_id")),
        )
        if decision.can_view:
            visible_ride_ids.append(str(ride.get("id")))
            visible_decisions.append((ride, decision.to_client_dict()))
    media_by_ride = await _feed_media_by_ride(repo, visible_ride_ids)
    activities = []
    for ride, privacy in visible_decisions:
        ride_for_event = await _ride_for_feed_event(
            ride,
            privacy,
            repo,
            media_by_ride.get(str(ride.get("id")), []),
        )
        event = build_ride_feed_event(
            ride_for_event,
            ride_users_by_id.get(ride.get("user_id")),
            summaries.get(str(ride.get("id"))),
            privacy,
        )
        if event:
            activities.append(event)
    if legacy_activities:
        legacy_user_ids = list({a.get("user_id") for a in legacy_activities if a.get("user_id")})
        legacy_users_by_id = {}
        if legacy_user_ids:
            legacy_users_by_id = await _feed_users_by_id(repo, legacy_user_ids, None)
        for activity in legacy_activities:
            activities.append(
                build_activity_feed_event(
                    activity,
                    legacy_users_by_id.get(activity.get("user_id")),
                )
            )

    activities = _sort_and_limit_events(activities, limit)
    return {
        "contractVersion": "feed.v1",
        "activities": activities,
        "has_more": len(rides) == limit or len(legacy_activities) == limit,
        "next_cursor": feed_cursor(activities),
    }


@router.get("/home")
async def get_home_feed(
    limit: int = Query(20, ge=1, le=50),
    before: Optional[datetime] = None,
    scope: str = Query("following", pattern="^(following|global)$"),
    sidecar_limit: int = Query(6, ge=1, le=12),
    current_user: Optional[AuthenticatedUser] = Depends(get_optional_current_user),
    repo: DatabaseRepository = Depends(get_repository),
    achievements_repo: AchievementRepository = Depends(get_achievement_repository),
):
    """One first-paint contract for Home/Feed surfaces."""
    feed_task = (
        get_feed(limit=limit, before=before, current_user=current_user, repo=repo)
        if current_user and scope == "following"
        else get_global_feed(limit=limit, before=before, repo=repo)
    )
    feed, suggested, climbs, achievements, social_counts, unread_count = await asyncio.gather(
        feed_task,
        _home_suggested_riders(repo, current_user, sidecar_limit),
        _home_popular_climbs(repo, sidecar_limit),
        _home_achievements(current_user, achievements_repo, sidecar_limit),
        _home_social_counts(repo, current_user.user_id) if current_user else asyncio.sleep(0, result={"followerCount": 0, "followingCount": 0}),
        _home_unread_count(current_user),
    )
    resolved_scope = scope if current_user or scope == "global" else "global"
    return {
        "contractVersion": "feed_home.v1",
        "scope": resolved_scope,
        "viewer": {
            "authenticated": current_user is not None,
            "userId": current_user.user_id if current_user else None,
            "wallet": current_user.wallet if current_user else None,
        },
        "feed": feed,
        "suggestedRiders": suggested,
        "popularClimbs": climbs,
        "achievements": achievements,
        "socialCounts": social_counts,
        "notifications": {
            "unreadCount": unread_count,
        },
    }


@router.get("/events")
async def get_feed_event_contract():
    """Return the canonical event names clients may render."""
    return {
        "contractVersion": "feed.v1",
        "eventTypes": [
            infer_activity_event_type(name).value
            for name in (
                "ride_completed",
                "climb_completed",
                "record_rank_moved",
                "local_legend_moved",
                "achievement_unlocked",
                "comment_created",
                "follow_created",
                "report_resolved",
            )
        ],
    }


async def create_activity(
    repo: DatabaseRepository,
    user_id: str,
    activity_type: str,
    title: str,
    description: Optional[str] = None,
    target_type: Optional[str] = None,
    target_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    is_public: bool = True,
):
    """Helper to create an activity record."""
    return await repo.create_activity(
        user_id=user_id,
        activity_type=activity_type,
        title=title,
        description=description,
        target_type=target_type,
        target_id=target_id,
        metadata=metadata,
        is_public=is_public,
    )
