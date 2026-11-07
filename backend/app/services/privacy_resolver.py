"""Central privacy and visibility policy for rider-facing surfaces.

Profile privacy controls whether a rider's profile shell and aggregate stats
are visible. Ride visibility controls activity detail visibility. Protocol
facts that are already chain-visible remain identified as public facts so
clients can render them deliberately instead of inferring policy from magic
fields.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional

from .ride_privacy import PrivacySettingsUnavailable, RidePrivacyPolicy


Visibility = Literal["public", "followers", "private"]

VALID_VISIBILITIES: set[str] = {"public", "followers", "private"}
MODERATION_HIDDEN_STATES: set[str] = {"hidden", "removed"}
PROTOCOL_PUBLIC_RIDE_FIELDS: tuple[str, ...] = (
    "ride_hash_hex",
    "attestation_commitment_hex",
    "ride_attestation_pda",
    "ride_attestation_tx_signature",
    "ride_attested_at",
    "finalized_at",
    "vault_completions",
)


def normalize_visibility(value: Any, default: Visibility = "public") -> Visibility:
    """Return a supported visibility value, falling back closed over garbage."""
    normalized = str(value or default).strip().lower()
    if normalized in VALID_VISIBILITIES:
        return normalized  # type: ignore[return-value]
    return default


def normalize_moderation_state(value: Any) -> str:
    normalized = str(value or "visible").strip().lower()
    if normalized in {"visible", "hidden", "removed"}:
        return normalized
    return "visible"


def is_moderated_hidden(row: dict[str, Any]) -> bool:
    return normalize_moderation_state(row.get("moderation_state")) in MODERATION_HIDDEN_STATES


def viewer_user_id(current_user_or_id: Any) -> Optional[str]:
    """Extract a user id from route auth objects without importing dependencies."""
    if current_user_or_id is None:
        return None
    if isinstance(current_user_or_id, str):
        return current_user_or_id
    user_id = getattr(current_user_or_id, "user_id", None)
    return str(user_id) if user_id else None


@dataclass(frozen=True)
class VisibilityDecision:
    can_view: bool
    visibility: Visibility
    reason: str
    is_owner: bool = False
    is_follower: bool = False
    redact_gps: bool = True
    map_visibility: str = "hide_entire"
    map_hide_start_m: int = 0
    map_hide_end_m: int = 0
    protocol_public_fields: tuple[str, ...] = ()

    @property
    def protocol_public(self) -> bool:
        return bool(self.protocol_public_fields)

    def to_client_dict(self) -> dict[str, Any]:
        return {
            "visibility": self.visibility,
            "canView": self.can_view,
            "isOwner": self.is_owner,
            "isFollower": self.is_follower,
            "redactGps": self.redact_gps,
            "mapVisibility": self.map_visibility,
            "mapHideStartM": self.map_hide_start_m,
            "mapHideEndM": self.map_hide_end_m,
            "protocolPublic": self.protocol_public,
            "protocolPublicFields": list(self.protocol_public_fields),
            "reason": self.reason,
        }


def _public_protocol_fields(row: dict[str, Any]) -> tuple[str, ...]:
    return tuple(
        field
        for field in PROTOCOL_PUBLIC_RIDE_FIELDS
        if row.get(field) not in (None, "", [], {})
    )


async def _is_follower(repo: Any, viewer_id: Optional[str], owner_id: Optional[str]) -> bool:
    if not viewer_id or not owner_id or not repo:
        return False
    get_follow = getattr(repo, "get_follow", None)
    if not get_follow:
        return False
    return bool(await get_follow(str(viewer_id), str(owner_id)))


async def resolve_ride_visibility(
    ride: dict[str, Any],
    current_user_or_id: Any = None,
    *,
    repo: Any = None,
    owner_profile: Optional[dict[str, Any]] = None,
) -> VisibilityDecision:
    """Resolve whether a viewer can see a ride and how clients should label it."""
    viewer_id = viewer_user_id(current_user_or_id)
    owner_id = ride.get("user_id") or ride.get("rider_id")
    owner_id = str(owner_id) if owner_id else None
    is_owner = bool(viewer_id and owner_id and viewer_id == owner_id)
    moderation_state = normalize_moderation_state(ride.get("moderation_state"))
    owner_moderation_state = normalize_moderation_state(
        (owner_profile or {}).get("moderation_state")
    )

    raw_visibility = ride.get("visibility")
    visibility = normalize_visibility(raw_visibility, default="private")
    try:
        map_policy = RidePrivacyPolicy.from_values(
            visibility=visibility,
            map_visibility=ride.get("map_visibility"),
            map_hide_start_m=ride.get("map_hide_start_m"),
            map_hide_end_m=ride.get("map_hide_end_m"),
        )
    except PrivacySettingsUnavailable:
        # Legacy or temporarily incomplete rows remain readable only with the
        # whole public map hidden. Never manufacture a less-private map mode.
        map_policy = RidePrivacyPolicy.from_values(
            visibility=visibility,
            map_visibility="hide_entire",
            map_hide_start_m=0,
            map_hide_end_m=0,
        )
    map_fields = {
        "map_visibility": map_policy.map_visibility,
        "map_hide_start_m": map_policy.map_hide_start_m,
        "map_hide_end_m": map_policy.map_hide_end_m,
    }
    protocol_fields = _public_protocol_fields(ride)

    if is_owner:
        return VisibilityDecision(
            can_view=True,
            visibility=visibility,
            reason="owner",
            is_owner=True,
            redact_gps=False,
            protocol_public_fields=protocol_fields,
            **map_fields,
        )

    if moderation_state in MODERATION_HIDDEN_STATES:
        return VisibilityDecision(
            can_view=False,
            visibility="private",
            reason=f"moderation_{moderation_state}",
            redact_gps=True,
            protocol_public_fields=protocol_fields,
            **map_fields,
        )

    if owner_moderation_state in MODERATION_HIDDEN_STATES:
        return VisibilityDecision(
            can_view=False,
            visibility="private",
            reason=f"owner_moderation_{owner_moderation_state}",
            redact_gps=True,
            protocol_public_fields=protocol_fields,
            **map_fields,
        )

    if visibility == "public":
        return VisibilityDecision(
            can_view=True,
            visibility=visibility,
            reason="public",
            redact_gps=True,
            protocol_public_fields=protocol_fields,
            **map_fields,
        )

    if visibility == "followers":
        follows = await _is_follower(repo, viewer_id, owner_id)
        return VisibilityDecision(
            can_view=follows,
            visibility=visibility,
            reason="follower" if follows else "not_follower",
            is_follower=follows,
            redact_gps=True,
            protocol_public_fields=protocol_fields,
            **map_fields,
        )

    return VisibilityDecision(
        can_view=False,
        visibility="private",
        reason="private",
        redact_gps=True,
        protocol_public_fields=protocol_fields,
        **map_fields,
    )


async def resolve_profile_visibility(
    profile: dict[str, Any],
    current_user_or_id: Any = None,
    *,
    repo: Any = None,
) -> VisibilityDecision:
    """Resolve whether a viewer can see a rider profile's full public shell."""
    viewer_id = viewer_user_id(current_user_or_id)
    owner_id = profile.get("id")
    owner_id = str(owner_id) if owner_id else None
    is_owner = bool(viewer_id and owner_id and viewer_id == owner_id)
    is_public = profile.get("is_public", True) is not False
    moderation_state = normalize_moderation_state(profile.get("moderation_state"))

    if is_owner:
        return VisibilityDecision(
            can_view=True,
            visibility="public" if is_public else "private",
            reason="owner",
            is_owner=True,
            redact_gps=False,
        )

    if moderation_state in MODERATION_HIDDEN_STATES:
        return VisibilityDecision(
            can_view=False,
            visibility="private",
            reason=f"moderation_{moderation_state}",
            redact_gps=True,
        )

    if is_public:
        follows = await _is_follower(repo, viewer_id, owner_id)
        return VisibilityDecision(
            can_view=True,
            visibility="public",
            reason="public_profile",
            is_follower=follows,
            redact_gps=True,
        )

    return VisibilityDecision(
        can_view=False,
        visibility="private",
        reason="private_profile",
        redact_gps=True,
    )
