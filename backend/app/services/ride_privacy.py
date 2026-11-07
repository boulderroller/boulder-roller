"""Strict ride privacy policy and server-side GPS projection.

Ride audience and map visibility are separate frozen properties.  This module
never invents a default when the persisted contract is incomplete: callers get
``PrivacySettingsUnavailable`` and must block the write or redact the read.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal, Mapping, Optional, Sequence


RideVisibility = Literal["public", "followers", "private"]
MapVisibility = Literal["show_all", "hide_start_end", "hide_entire"]

VALID_RIDE_VISIBILITIES: set[str] = {"public", "followers", "private"}
VALID_MAP_VISIBILITIES: set[str] = {
    "show_all",
    "hide_start_end",
    "hide_entire",
}
ALLOWED_MAP_HIDE_DISTANCES_M: set[int] = {0, 200, 400, 800, 1600}
ALLOWED_PRIVACY_ZONE_RADII_M: set[int] = {200, 400, 800, 1600}

_EARTH_RADIUS_M = 6_371_000.0
# Treat a route that comes within roughly six millimeters of a zone boundary as
# touching it.  The tolerance absorbs floating-point error at tangencies while
# remaining immaterial next to the smallest supported 200 meter zone.
_GEOMETRY_TOLERANCE_RAD = 1e-9


class PrivacySettingsUnavailable(RuntimeError):
    """The complete privacy contract could not be safely resolved."""


def _strict_choice(value: Any, allowed: set[str], field: str) -> str:
    if not isinstance(value, str) or value not in allowed:
        raise PrivacySettingsUnavailable(f"invalid or missing {field}")
    return value


def _strict_distance(value: Any, field: str) -> int:
    # bool is an int subclass, but accepting it here would silently turn a
    # malformed transport value into a privacy distance.
    if type(value) is not int or value not in ALLOWED_MAP_HIDE_DISTANCES_M:
        raise PrivacySettingsUnavailable(f"invalid or missing {field}")
    return value


@dataclass(frozen=True)
class RidePrivacyPolicy:
    """A complete, validated privacy snapshot for one ride."""

    visibility: RideVisibility
    map_visibility: MapVisibility
    map_hide_start_m: int
    map_hide_end_m: int

    def __post_init__(self) -> None:
        _strict_choice(self.visibility, VALID_RIDE_VISIBILITIES, "visibility")
        _strict_choice(
            self.map_visibility,
            VALID_MAP_VISIBILITIES,
            "map_visibility",
        )
        _strict_distance(self.map_hide_start_m, "map_hide_start_m")
        _strict_distance(self.map_hide_end_m, "map_hide_end_m")
        if self.map_visibility == "hide_start_end" and (
            self.map_hide_start_m == 0 or self.map_hide_end_m == 0
        ):
            raise PrivacySettingsUnavailable(
                "hide_start_end requires a non-zero distance at both endpoints"
            )

    @classmethod
    def from_values(
        cls,
        *,
        visibility: Any,
        map_visibility: Any,
        map_hide_start_m: Any,
        map_hide_end_m: Any,
    ) -> "RidePrivacyPolicy":
        """Build a policy only from four explicit, valid values."""
        return cls(
            visibility=_strict_choice(
                visibility,
                VALID_RIDE_VISIBILITIES,
                "visibility",
            ),  # type: ignore[arg-type]
            map_visibility=_strict_choice(
                map_visibility,
                VALID_MAP_VISIBILITIES,
                "map_visibility",
            ),  # type: ignore[arg-type]
            map_hide_start_m=_strict_distance(
                map_hide_start_m,
                "map_hide_start_m",
            ),
            map_hide_end_m=_strict_distance(
                map_hide_end_m,
                "map_hide_end_m",
            ),
        )

    def to_storage_dict(self) -> dict[str, Any]:
        return {
            "visibility": self.visibility,
            "map_visibility": self.map_visibility,
            "map_hide_start_m": self.map_hide_start_m,
            "map_hide_end_m": self.map_hide_end_m,
        }

    def to_client_dict(self) -> dict[str, Any]:
        return {
            "visibility": self.visibility,
            "mapVisibility": self.map_visibility,
            "mapHideStartM": self.map_hide_start_m,
            "mapHideEndM": self.map_hide_end_m,
        }


def _pick_policy_value(
    defaults: Mapping[str, Any],
    overrides: Mapping[str, Any],
    ride_key: str,
    default_key: str,
) -> Any:
    if ride_key in overrides:
        return overrides[ride_key]
    if default_key in defaults:
        return defaults[default_key]
    if ride_key in defaults:
        return defaults[ride_key]
    raise PrivacySettingsUnavailable(f"missing {default_key}")


def resolve_policy(
    defaults: Mapping[str, Any],
    overrides: Optional[Mapping[str, Any]] = None,
) -> RidePrivacyPolicy:
    """Resolve explicit ride overrides over a complete account default row.

    ``None`` or a missing key is never converted into a public/show-all policy.
    A key explicitly supplied as ``None`` is invalid rather than treated as an
    omitted override.
    """
    if not isinstance(defaults, Mapping):
        raise PrivacySettingsUnavailable("privacy defaults unavailable")
    if overrides is None:
        overrides = {}
    if not isinstance(overrides, Mapping):
        raise PrivacySettingsUnavailable("privacy overrides unavailable")

    return RidePrivacyPolicy.from_values(
        visibility=_pick_policy_value(
            defaults,
            overrides,
            "visibility",
            "default_ride_visibility",
        ),
        map_visibility=_pick_policy_value(
            defaults,
            overrides,
            "map_visibility",
            "default_map_visibility",
        ),
        map_hide_start_m=_pick_policy_value(
            defaults,
            overrides,
            "map_hide_start_m",
            "default_map_hide_start_m",
        ),
        map_hide_end_m=_pick_policy_value(
            defaults,
            overrides,
            "map_hide_end_m",
            "default_map_hide_end_m",
        ),
    )


def haversine_meters(
    latitude_a: float,
    longitude_a: float,
    latitude_b: float,
    longitude_b: float,
) -> float:
    """Return great-circle distance in meters between two WGS84 coordinates."""
    lat_a = math.radians(latitude_a)
    lat_b = math.radians(latitude_b)
    delta_lat = lat_b - lat_a
    delta_lon = math.radians(longitude_b - longitude_a)
    haversine = (
        math.sin(delta_lat / 2.0) ** 2
        + math.cos(lat_a) * math.cos(lat_b) * math.sin(delta_lon / 2.0) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return 2.0 * _EARTH_RADIUS_M * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1.0 - haversine),
    )


def _unit_vector(
    coordinate: tuple[float, float],
) -> tuple[float, float, float]:
    latitude = math.radians(coordinate[0])
    longitude = math.radians(coordinate[1])
    cos_latitude = math.cos(latitude)
    return (
        cos_latitude * math.cos(longitude),
        cos_latitude * math.sin(longitude),
        math.sin(latitude),
    )


def _dot(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    return left[0] * right[0] + left[1] * right[1] + left[2] * right[2]


def _cross(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> tuple[float, float, float]:
    return (
        left[1] * right[2] - left[2] * right[1],
        left[2] * right[0] - left[0] * right[2],
        left[0] * right[1] - left[1] * right[0],
    )


def _norm(vector: tuple[float, float, float]) -> float:
    return math.sqrt(_dot(vector, vector))


def _angular_distance(
    left: tuple[float, float, float],
    right: tuple[float, float, float],
) -> float:
    # atan2 is stable for the short segments common in GPS tracks while still
    # handling dateline crossings and long arcs correctly.
    return math.atan2(
        _norm(_cross(left, right)),
        min(1.0, max(-1.0, _dot(left, right))),
    )


def _segment_intersects_zone(
    start: tuple[float, float],
    end: tuple[float, float],
    zone: tuple[float, float, int],
) -> bool:
    """Return whether a shortest great-circle segment touches a zone.

    Callers use this only when both samples are outside the circle.  Segments
    with indistinguishable antipodal endpoints have no unique shortest arc, so
    they fail closed rather than guessing which half of the globe was drawn.
    """
    start_vector = _unit_vector(start)
    end_vector = _unit_vector(end)
    zone_vector = _unit_vector((zone[0], zone[1]))
    radius_rad = zone[2] / _EARTH_RADIUS_M

    segment_angle = _angular_distance(start_vector, end_vector)
    if segment_angle <= _GEOMETRY_TOLERANCE_RAD:
        return False

    normal = _cross(start_vector, end_vector)
    normal_length = _norm(normal)
    if normal_length <= _GEOMETRY_TOLERANCE_RAD:
        return _dot(start_vector, end_vector) < 0.0
    unit_normal = tuple(component / normal_length for component in normal)

    # Project the zone center onto the segment's great circle.  There are two
    # antipodal projections; only a projection on the minor start/end arc can
    # be the segment's closest point.
    normal_component = _dot(zone_vector, unit_normal)
    projection = tuple(
        zone_vector[index] - normal_component * unit_normal[index]
        for index in range(3)
    )
    projection_length = _norm(projection)
    if projection_length <= _GEOMETRY_TOLERANCE_RAD:
        # The zone center is a pole of this great circle, so its distance to
        # every point on the circle is 90 degrees (far beyond supported zones).
        return False

    nearest = tuple(component / projection_length for component in projection)
    for candidate in (nearest, tuple(-component for component in nearest)):
        start_to_candidate = _angular_distance(start_vector, candidate)
        candidate_to_end = _angular_distance(candidate, end_vector)
        if (
            abs(
                start_to_candidate
                + candidate_to_end
                - segment_angle
            )
            > _GEOMETRY_TOLERANCE_RAD
        ):
            continue
        if (
            _angular_distance(zone_vector, candidate)
            <= radius_rad + _GEOMETRY_TOLERANCE_RAD
        ):
            return True
    return False


def _coordinate(point: Mapping[str, Any]) -> Optional[tuple[float, float]]:
    try:
        latitude = float(point.get("latitude"))
        longitude = float(point.get("longitude"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    if not -90.0 <= latitude <= 90.0 or not -180.0 <= longitude <= 180.0:
        return None
    return latitude, longitude


def _redact_point(point: Mapping[str, Any]) -> dict[str, Any]:
    redacted = dict(point)
    redacted["latitude"] = None
    redacted["longitude"] = None
    if "lat" in redacted:
        redacted["lat"] = None
    if "lng" in redacted:
        redacted["lng"] = None
    if "lon" in redacted:
        redacted["lon"] = None
    redacted["redacted"] = True
    return redacted


# Keys a hidden point may keep when it leaves the API: its place along the
# ride (so clients can draw the gap) and the flag itself.
_HIDDEN_POINT_KEEP = frozenset({"distance_m", "distanceM", "redacted"})


def strip_hidden_point_details(points: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Return the viewer-facing copy of projected points.

    `project_route_points` keeps timestamps on hidden points because the
    public-record span check (`route_span_is_public`) needs a complete time
    axis. That projection is internal. What leaves the API for another rider
    must not let them locate a hidden start, end, or privacy zone, so every
    field of a hidden point except its distance and the flag becomes null.
    Keys are kept so clients see the same shape.
    """
    public: list[dict[str, Any]] = []
    for point in points:
        copied = dict(point)
        if copied.get("redacted") is True:
            copied = {key: (value if key in _HIDDEN_POINT_KEEP else None) for key, value in copied.items()}
        public.append(copied)
    return public


def _validated_zones(
    privacy_zones: Sequence[Mapping[str, Any]],
) -> tuple[tuple[float, float, int], ...]:
    zones: list[tuple[float, float, int]] = []
    for zone in privacy_zones:
        if not isinstance(zone, Mapping):
            raise PrivacySettingsUnavailable("invalid privacy zone")
        coordinate = _coordinate(zone)
        radius_m = zone.get("radius_m")
        if (
            coordinate is None
            or type(radius_m) is not int
            or radius_m not in ALLOWED_PRIVACY_ZONE_RADII_M
        ):
            raise PrivacySettingsUnavailable("invalid privacy zone")
        zones.append((coordinate[0], coordinate[1], radius_m))
    return tuple(zones)


def _route_distances(
    coordinates: Sequence[Optional[tuple[float, float]]],
) -> tuple[dict[int, float], float]:
    cumulative_by_index: dict[int, float] = {}
    prior: Optional[tuple[float, float]] = None
    cumulative = 0.0
    for index, coordinate in enumerate(coordinates):
        if coordinate is None:
            continue
        if prior is not None:
            cumulative += haversine_meters(
                prior[0],
                prior[1],
                coordinate[0],
                coordinate[1],
            )
        cumulative_by_index[index] = cumulative
        prior = coordinate
    return cumulative_by_index, cumulative


def project_route_points(
    points: Sequence[Mapping[str, Any]],
    policy: RidePrivacyPolicy,
    *,
    privacy_zones: Optional[Sequence[Mapping[str, Any]]] = (),
    is_owner: bool = False,
) -> list[dict[str, Any]]:
    """Return a privacy projection without deleting or reconnecting points.

    Redacted points stay in their original positions with coordinates nulled,
    so clients can split the route into visible runs instead of drawing a line
    across a hidden endpoint or interior privacy zone.
    """
    if not isinstance(policy, RidePrivacyPolicy):
        raise PrivacySettingsUnavailable("ride privacy policy unavailable")

    copied = [dict(point) for point in points]
    if is_owner:
        return copied

    if privacy_zones is None:
        raise PrivacySettingsUnavailable("privacy zones unavailable")
    zones = _validated_zones(privacy_zones)
    coordinates = [_coordinate(point) for point in copied]

    if policy.map_visibility == "hide_entire":
        return [_redact_point(point) for point in copied]

    cumulative_by_index, total_distance_m = _route_distances(coordinates)
    zone_redactions = [False] * len(copied)
    for zone in zones:
        inside_zone = [
            coordinate is not None
            and haversine_meters(
                coordinate[0],
                coordinate[1],
                zone[0],
                zone[1],
            )
            <= zone[2] + _EARTH_RADIUS_M * _GEOMETRY_TOLERANCE_RAD
            for coordinate in coordinates
        ]
        for index, is_inside in enumerate(inside_zone):
            zone_redactions[index] = zone_redactions[index] or is_inside

        for index in range(len(coordinates) - 1):
            start = coordinates[index]
            end = coordinates[index + 1]
            if (
                start is None
                or end is None
                or inside_zone[index]
                or inside_zone[index + 1]
            ):
                # An inside/boundary sample is already nulled and therefore
                # splits the segment without expanding the gap unnecessarily.
                continue
            if _segment_intersects_zone(start, end, zone):
                # Neither sparse endpoint reveals which side of the hidden
                # circle the rider traversed.  Null both in place so clients
                # cannot draw the crossing and span checks reject the interval.
                zone_redactions[index] = True
                zone_redactions[index + 1] = True

    projected: list[dict[str, Any]] = []

    for index, point in enumerate(copied):
        coordinate = coordinates[index]
        should_redact = (
            coordinate is None
            or point.get("redacted") is True
            or zone_redactions[index]
        )

        if (
            not should_redact
            and policy.map_visibility == "hide_start_end"
        ):
            distance_from_start_m = cumulative_by_index[index]
            distance_from_end_m = total_distance_m - distance_from_start_m
            should_redact = (
                policy.map_hide_start_m > 0
                and distance_from_start_m <= policy.map_hide_start_m
            ) or (
                policy.map_hide_end_m > 0
                and distance_from_end_m <= policy.map_hide_end_m
            )

        projected.append(_redact_point(point) if should_redact else point)

    return projected
