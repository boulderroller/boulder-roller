"""
Climb Signature System

Creates 64-byte fingerprints for climb profiles that can be used to:
1. Match user rides against canonical climbs from a vault
2. Detect when different routes traverse the same climb
3. Create on-chain attestations for verified climbs

Signature Structure (64 bytes):
- Bytes 0-31:  Gradient profile hash (32 bins of normalized gradient)
- Bytes 32-35: Total vertical gain (float32, big-endian)
- Bytes 36-39: Average gradient % (float32, big-endian)
- Bytes 40-43: Distance meters (float32, big-endian)
- Bytes 44-47: Duration seconds (uint32, big-endian)
- Bytes 48-63: Reserved / checksum

The gradient profile is route-agnostic - it captures the "shape" of the climb
without encoding exact GPS coordinates. This allows matching climbs that
take different roads up the same mountain.

Avoiding Strava IP:
- We use OSM data for canonical climbs, not user-generated segments
- Signatures are computed from elevation profiles, not exact routes
- No "segment" concept - we match elevation shapes
"""

from __future__ import annotations

import hashlib
import importlib
import math
import struct
from dataclasses import dataclass
from typing import Any, Callable, List, Optional, Tuple

from app.services.sample_time import (
    infer_sample_time_base,
    sample_in_time_window,
    sample_time_seconds,
)

@dataclass
class ClimbSignature:
    """
    A 64-byte fingerprint representing a climb's profile.

    Can be used for:
    - Matching against canonical climbs
    - On-chain attestation
    - Deduplication
    """
    signature: bytes  # 64 bytes

    # Decoded values for convenience
    vert_m: float
    avg_gradient_pct: float
    distance_m: float
    duration_s: int

    def __post_init__(self):
        if len(self.signature) != 64:
            raise ValueError(f"Signature must be 64 bytes, got {len(self.signature)}")

    @property
    def hex(self) -> str:
        """Return signature as hex string."""
        return self.signature.hex()

    @property
    def gradient_profile_hash(self) -> bytes:
        """First 32 bytes - the gradient shape hash."""
        return self.signature[:32]

    def similarity(self, other: "ClimbSignature") -> float:
        """
        Calculate similarity score between two signatures.

        Returns 0.0 to 1.0 where 1.0 is identical.
        Uses hamming distance on gradient hash + metric comparison.
        """
        # Hamming distance on gradient profile (32 bytes = 256 bits)
        xor = bytes(a ^ b for a, b in zip(self.gradient_profile_hash, other.gradient_profile_hash))
        bit_diff = sum(bin(byte).count('1') for byte in xor)
        gradient_sim = 1.0 - (bit_diff / 256.0)

        # Metric similarity (vert, gradient, distance)
        vert_sim = 1.0 - min(1.0, abs(self.vert_m - other.vert_m) / max(self.vert_m, other.vert_m, 1))
        grad_sim = 1.0 - min(1.0, abs(self.avg_gradient_pct - other.avg_gradient_pct) / 20.0)
        dist_sim = 1.0 - min(1.0, abs(self.distance_m - other.distance_m) / max(self.distance_m, other.distance_m, 1))

        # Weighted combination
        return 0.5 * gradient_sim + 0.2 * vert_sim + 0.2 * grad_sim + 0.1 * dist_sim

    def to_dict(self) -> dict:
        return {
            "signature_hex": self.hex,
            "vert_m": round(self.vert_m, 1),
            "avg_gradient_pct": round(self.avg_gradient_pct, 1),
            "distance_m": round(self.distance_m, 0),
            "duration_s": self.duration_s,
        }


class ClimbSignatureGenerator:
    """
    Generates 64-byte signatures from climb data.
    """

    # Number of bins for gradient profile
    GRADIENT_BINS = 32

    # Gradient range for binning (-10% to +20%)
    GRADIENT_MIN = -10.0
    GRADIENT_MAX = 20.0

    def generate(
        self,
        elevations: List[float],
        timestamps: List[int],
        distances: Optional[List[float]] = None,
    ) -> ClimbSignature:
        """
        Generate a signature from elevation profile data.

        Args:
            elevations: Elevation values in meters (smoothed recommended)
            timestamps: Unix timestamps or seconds-from-start
            distances: Optional cumulative distance in meters
                      (if not provided, estimated from time at 5m/s)

        Returns:
            ClimbSignature with 64-byte fingerprint
        """
        if len(elevations) < 2:
            raise ValueError("Need at least 2 elevation points")

        if len(elevations) != len(timestamps):
            raise ValueError("Elevations and timestamps must have same length")

        n = len(elevations)

        # Calculate or use distances
        if distances is None:
            # Estimate from time at ~5 m/s
            distances = [0.0]
            for i in range(1, n):
                dt = timestamps[i] - timestamps[i-1]
                distances.append(distances[-1] + abs(dt) * 5.0)

        total_distance = distances[-1] - distances[0]
        if total_distance <= 0:
            total_distance = 1.0

        # Calculate total vertical gain
        total_vert = 0.0
        for i in range(1, n):
            delta = elevations[i] - elevations[i-1]
            if delta > 0:
                total_vert += delta

        # Calculate average gradient
        total_elev_change = elevations[-1] - elevations[0]
        avg_gradient = (total_elev_change / total_distance) * 100.0 if total_distance > 0 else 0.0

        # Duration
        duration_s = timestamps[-1] - timestamps[0]

        # Build gradient profile (32 bins)
        gradient_profile = self._build_gradient_profile(elevations, distances)

        # Hash the gradient profile to 32 bytes
        profile_hash = hashlib.sha256(gradient_profile).digest()

        # Pack metrics
        vert_bytes = struct.pack('>f', total_vert)
        grad_bytes = struct.pack('>f', avg_gradient)
        dist_bytes = struct.pack('>f', total_distance)
        dur_bytes = struct.pack('>I', max(0, duration_s))

        # Reserved/checksum (16 bytes)
        data_to_hash = profile_hash + vert_bytes + grad_bytes + dist_bytes + dur_bytes
        checksum = hashlib.md5(data_to_hash).digest()

        # Assemble 64-byte signature
        signature = profile_hash + vert_bytes + grad_bytes + dist_bytes + dur_bytes + checksum

        return ClimbSignature(
            signature=signature,
            vert_m=total_vert,
            avg_gradient_pct=avg_gradient,
            distance_m=total_distance,
            duration_s=duration_s,
        )

    def _build_gradient_profile(
        self,
        elevations: List[float],
        distances: List[float],
    ) -> bytes:
        """
        Build a normalized gradient profile as bytes.

        Divides the climb into GRADIENT_BINS segments and computes
        average gradient for each. Returns as bytes for hashing.
        """
        n = len(elevations)
        total_dist = distances[-1] - distances[0]

        if total_dist <= 0:
            return bytes(self.GRADIENT_BINS)

        bin_size = total_dist / self.GRADIENT_BINS
        profile = []

        for bin_idx in range(self.GRADIENT_BINS):
            bin_start_dist = distances[0] + bin_idx * bin_size
            bin_end_dist = bin_start_dist + bin_size

            # Find elevation change in this bin
            start_elev = self._interpolate_elevation(distances, elevations, bin_start_dist)
            end_elev = self._interpolate_elevation(distances, elevations, bin_end_dist)

            elev_change = end_elev - start_elev
            gradient_pct = (elev_change / bin_size) * 100.0 if bin_size > 0 else 0.0

            # Normalize to 0-255 range
            normalized = (gradient_pct - self.GRADIENT_MIN) / (self.GRADIENT_MAX - self.GRADIENT_MIN)
            normalized = max(0.0, min(1.0, normalized))
            byte_val = int(normalized * 255)

            profile.append(byte_val)

        return bytes(profile)

    def _interpolate_elevation(
        self,
        distances: List[float],
        elevations: List[float],
        target_dist: float,
    ) -> float:
        """Linear interpolation to get elevation at a specific distance."""
        if target_dist <= distances[0]:
            return elevations[0]
        if target_dist >= distances[-1]:
            return elevations[-1]

        for i in range(1, len(distances)):
            if distances[i] >= target_dist:
                # Interpolate between i-1 and i
                d0, d1 = distances[i-1], distances[i]
                e0, e1 = elevations[i-1], elevations[i]

                if d1 == d0:
                    return e0

                t = (target_dist - d0) / (d1 - d0)
                return e0 + t * (e1 - e0)

        return elevations[-1]

    def generate_from_climb_pattern(
        self,
        tile_samples: List[dict],
        start_time: int,
        end_time: int,
    ) -> Optional[ClimbSignature]:
        """
        Generate signature from tile samples within a time range.

        Convenience method that extracts elevation/time data from
        the standard tile sample format.
        """
        base_time = infer_sample_time_base(tile_samples)

        # Filter samples in time range with elevation
        samples = [
            s for s in tile_samples
            if s.get("elevation_m") is not None
            and sample_in_time_window(s, start_time, end_time, base_time=base_time)
        ]

        if len(samples) < 2:
            return None

        samples = sorted(
            samples,
            key=lambda s: sample_time_seconds(s.get("t"), base_time=base_time) or 0.0,
        )

        elevations = [float(s["elevation_m"]) for s in samples]
        timestamps = [
            int(round(sample_time_seconds(s.get("t"), base_time=base_time) or 0.0))
            for s in samples
        ]

        # Try to get distances from lat/lon if available
        distances = None
        if all(s.get("lat") is not None and s.get("lon") is not None for s in samples):
            distances = [0.0]
            for i in range(1, len(samples)):
                d = self._haversine(
                    samples[i-1]["lat"], samples[i-1]["lon"],
                    samples[i]["lat"], samples[i]["lon"]
                )
                distances.append(distances[-1] + d)

        return self.generate(elevations, timestamps, distances)

    def _haversine(self, lat1: float, lon1: float, lat2: float, lon2: float) -> float:
        """Calculate distance in meters between two lat/lon points."""
        R = 6371000
        phi1, phi2 = math.radians(lat1), math.radians(lat2)
        dphi = math.radians(lat2 - lat1)
        dlambda = math.radians(lon2 - lon1)
        a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
        return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# ---------------------------------------------------------------------------
# V2 Signature (DCT-II + BLAKE3)
# ---------------------------------------------------------------------------


class RewardGradeMatcherError(RuntimeError):
    """Raised when the native reward-grade matcher cannot return a verdict."""


class RewardGradeMatcherUnavailable(RewardGradeMatcherError):
    """Raised when the native v2 matcher required for economics is unavailable."""


class AmbiguousRewardGradeVaultMatch(RewardGradeMatcherError):
    """Raised when more than one active vault can receive one completion."""


class InvalidRewardGradeEvidence(ValueError):
    """Base class for malformed reward-grade climb evidence."""


class InvalidRewardGradeQuery(InvalidRewardGradeEvidence):
    """Raised when the detected climb's reward-grade evidence is malformed."""


class InvalidRewardGradeCandidate(InvalidRewardGradeEvidence):
    """Raised when a candidate vault's reward-grade evidence is malformed."""


REWARD_GRADE_MIN_SIMILARITY = 0.90


@dataclass(frozen=True)
class RewardGradeMatchEvidence:
    """Auditable evidence returned by the one reward-grade matching path."""

    result: str
    similarity: float
    confidence: float
    dct_distance: float
    start_distance_m: float
    end_distance_m: float

    def to_dict(self) -> dict:
        return {
            "result": self.result,
            "similarity": self.similarity,
            "confidence": self.confidence,
            "dct_distance": self.dct_distance,
            "start_distance_m": self.start_distance_m,
            "end_distance_m": self.end_distance_m,
        }


def _load_v2_matcher() -> Callable[[str, str], dict]:
    try:
        workout_parse = importlib.import_module("workout_parse")
    except (ImportError, ModuleNotFoundError) as exc:
        raise RewardGradeMatcherUnavailable(
            "workout_parse is required for reward-grade v2 climb matching"
        ) from exc

    matcher = getattr(workout_parse, "match_signatures_v2", None)
    if not callable(matcher):
        raise RewardGradeMatcherUnavailable(
            "workout_parse.match_signatures_v2 is unavailable"
        )
    return matcher


def _validate_native_signature(
    *,
    matcher: Callable[[str, str], dict],
    signature: "ClimbSignatureV2",
    role: str,
) -> None:
    error_type = (
        InvalidRewardGradeQuery if role == "query" else InvalidRewardGradeCandidate
    )
    try:
        result = matcher(signature.hex, signature.hex)
    except ValueError as exc:
        raise error_type(f"{role} v2 signature checksum is invalid") from exc
    except Exception as exc:
        raise RewardGradeMatcherError(
            f"reward-grade v2 matcher failed while validating {role}"
        ) from exc
    if not isinstance(result, dict):
        raise RewardGradeMatcherError(
            f"v2 matcher returned an invalid {role} validation result"
        )
    similarity = _similarity_from_v2_result(result)
    if similarity < REWARD_GRADE_MIN_SIMILARITY:
        raise error_type(f"{role} v2 signature failed native self-validation")


def validate_reward_grade_v2_native(
    *,
    signature_v2_hex: str,
    role: str,
) -> "ClimbSignatureV2":
    """Validate one v2 checksum even when there are no match candidates."""
    if role not in ("query", "candidate"):
        raise ValueError("reward-grade signature role must be query or candidate")
    signature = ClimbSignatureV2.from_hex(signature_v2_hex)
    if signature is None:
        error_type = (
            InvalidRewardGradeQuery
            if role == "query"
            else InvalidRewardGradeCandidate
        )
        raise error_type(f"{role} v2 signature is invalid")
    _validate_native_signature(
        matcher=_load_v2_matcher(),
        signature=signature,
        role=role,
    )
    return signature


def _validated_point(label: str, point: Tuple[Any, Any]) -> Tuple[float, float]:
    if point is None or len(point) != 2:
        raise ValueError(f"{label} GPS point is required")
    try:
        lat = float(point[0])
        lon = float(point[1])
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} GPS point is required") from exc
    if not math.isfinite(lat) or not math.isfinite(lon):
        raise ValueError(f"{label} GPS point must be finite")
    if not -90.0 <= lat <= 90.0 or not -180.0 <= lon <= 180.0:
        raise ValueError(f"{label} GPS point is out of range")
    if lat == 0.0 and lon == 0.0:
        raise ValueError(f"{label} GPS point cannot be the no-fix (0, 0) sentinel")
    return lat, lon


def _haversine_m(
    point_a: Tuple[float, float],
    point_b: Tuple[float, float],
) -> float:
    lat_a, lon_a = point_a
    lat_b, lon_b = point_b
    earth_radius_m = 6_371_000.0
    phi_a = math.radians(lat_a)
    phi_b = math.radians(lat_b)
    delta_phi = math.radians(lat_b - lat_a)
    delta_lambda = math.radians(lon_b - lon_a)
    haversine = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi_a)
        * math.cos(phi_b)
        * math.sin(delta_lambda / 2.0) ** 2
    )
    haversine = min(1.0, max(0.0, haversine))
    return earth_radius_m * 2.0 * math.atan2(
        math.sqrt(haversine),
        math.sqrt(1.0 - haversine),
    )


def _similarity_from_v2_result(result: dict) -> float:
    result_name = result.get("result")
    try:
        confidence = float(result.get("confidence", 0.0))
    except (TypeError, ValueError) as exc:
        raise RewardGradeMatcherError(
            "v2 matcher returned invalid confidence"
        ) from exc
    if not math.isfinite(confidence) or not 0.0 <= confidence <= 1.0:
        raise RewardGradeMatcherError("v2 matcher returned invalid confidence")
    if result_name == "match":
        return 0.95 + 0.05 * confidence
    if result_name == "probable_match":
        return 0.85 + 0.10 * confidence
    if result_name in ("no_match", "incompatible"):
        return 0.0
    raise RewardGradeMatcherError("v2 matcher returned an unknown result")


def validate_reward_grade_climb_evidence(
    *,
    signature_v2_hex: str,
    start: Tuple[Any, Any],
    end: Tuple[Any, Any],
    label: str,
) -> Tuple["ClimbSignatureV2", Tuple[float, float], Tuple[float, float]]:
    signature = ClimbSignatureV2.from_hex(signature_v2_hex)
    if signature is None:
        raise ValueError(f"{label} v2 signature is invalid")
    if signature.vert_m <= 0 or signature.distance_m <= 0:
        raise ValueError(f"{label} v2 signature has invalid geometry")
    return (
        signature,
        _validated_point(f"{label} start", start),
        _validated_point(f"{label} end", end),
    )


def match_reward_grade_v2(
    *,
    query_signature_v2_hex: str,
    candidate_signature_v2_hex: str,
    query_start: Tuple[Any, Any],
    query_end: Tuple[Any, Any],
    candidate_start: Tuple[Any, Any],
    candidate_end: Tuple[Any, Any],
    max_endpoint_distance_m: float = 150.0,
) -> Optional[RewardGradeMatchEvidence]:
    """Match one climb to one vault using v2 shape plus oriented endpoints.

    Reward-bearing callers must use this function. Legacy v1 matching remains
    available only for discovery and display attribution.
    """
    try:
        query_signature, query_start_point, query_end_point = (
            validate_reward_grade_climb_evidence(
                signature_v2_hex=query_signature_v2_hex,
                start=query_start,
                end=query_end,
                label="query",
            )
        )
    except ValueError as exc:
        raise InvalidRewardGradeQuery(str(exc)) from exc
    try:
        candidate_signature, candidate_start_point, candidate_end_point = (
            validate_reward_grade_climb_evidence(
                signature_v2_hex=candidate_signature_v2_hex,
                start=candidate_start,
                end=candidate_end,
                label="candidate",
            )
        )
    except ValueError as exc:
        raise InvalidRewardGradeCandidate(str(exc)) from exc

    if (
        not math.isfinite(max_endpoint_distance_m)
        or max_endpoint_distance_m <= 0.0
    ):
        raise ValueError("max endpoint distance must be positive and finite")

    matcher = _load_v2_matcher()
    _validate_native_signature(
        matcher=matcher,
        signature=query_signature,
        role="query",
    )
    _validate_native_signature(
        matcher=matcher,
        signature=candidate_signature,
        role="candidate",
    )
    start_distance_m = _haversine_m(query_start_point, candidate_start_point)
    end_distance_m = _haversine_m(query_end_point, candidate_end_point)
    if (
        start_distance_m > max_endpoint_distance_m
        or end_distance_m > max_endpoint_distance_m
    ):
        return None

    try:
        result = matcher(query_signature.hex, candidate_signature.hex)
    except ValueError as exc:
        message = str(exc)
        if "(a)" in message:
            raise InvalidRewardGradeQuery(
                "query v2 signature checksum is invalid"
            ) from exc
        if "(b)" in message:
            raise InvalidRewardGradeCandidate(
                "candidate v2 signature checksum is invalid"
            ) from exc
        raise RewardGradeMatcherError(
            "reward-grade v2 matcher rejected the evidence"
        ) from exc
    except Exception as exc:
        raise RewardGradeMatcherError("reward-grade v2 matcher failed") from exc
    if not isinstance(result, dict):
        raise RewardGradeMatcherError(
            "reward-grade v2 matcher returned an invalid result"
        )

    similarity = _similarity_from_v2_result(result)
    if similarity == 0.0:
        return None

    try:
        dct_distance = float(result.get("dct_distance", 0.0))
    except (TypeError, ValueError) as exc:
        raise RewardGradeMatcherError(
            "v2 matcher returned invalid DCT distance"
        ) from exc
    if not math.isfinite(dct_distance) or dct_distance < 0.0:
        raise RewardGradeMatcherError("v2 matcher returned invalid DCT distance")

    return RewardGradeMatchEvidence(
        result=str(result["result"]),
        similarity=similarity,
        confidence=float(result.get("confidence", 0.0)),
        dct_distance=dct_distance,
        start_distance_m=start_distance_m,
        end_distance_m=end_distance_m,
    )

@dataclass
class ClimbSignatureV2:
    """
    A 64-byte DCT-II climb signature (version 2).

    Layout: version(1) + flags(1) + vert(2) + dist(2) + grad(2) + h3_anchor(8)
            + dct_f16[16](32) + blake3(16) = 64 bytes.

    Version discrimination: v1 signatures have no version byte; v2 starts with 0x02.
    Do NOT sniff bytes to distinguish versions — use the column (signature_hex = v1,
    signature_v2_hex = v2).
    """
    signature: bytes  # 64 bytes

    # Decoded fields
    vert_m: int
    distance_m: int
    avg_gradient_x100: int
    h3_anchor: int

    def __post_init__(self):
        if len(self.signature) != 64:
            raise ValueError(f"V2 signature must be 64 bytes, got {len(self.signature)}")
        if self.signature[0] != 0x02:
            raise ValueError(f"V2 signature must start with 0x02, got 0x{self.signature[0]:02x}")

    @classmethod
    def from_hex(cls, hex_str: str) -> Optional["ClimbSignatureV2"]:
        """Decode a v2 signature from hex string. Returns None if invalid."""
        try:
            sig_bytes = bytes.fromhex(hex_str)
            if len(sig_bytes) != 64 or sig_bytes[0] != 0x02:
                return None
            vert_m = struct.unpack(">H", sig_bytes[2:4])[0]
            distance_m = struct.unpack(">H", sig_bytes[4:6])[0] * 10
            avg_gradient_x100 = struct.unpack(">h", sig_bytes[6:8])[0]
            h3_anchor = struct.unpack(">Q", sig_bytes[8:16])[0]
            return cls(
                signature=sig_bytes,
                vert_m=vert_m,
                distance_m=distance_m,
                avg_gradient_x100=avg_gradient_x100,
                h3_anchor=h3_anchor,
            )
        except (TypeError, ValueError, struct.error):
            return None

    @property
    def hex(self) -> str:
        return self.signature.hex()

    @property
    def avg_gradient_pct(self) -> float:
        return self.avg_gradient_x100 / 100.0

    def similarity(self, other: "ClimbSignatureV2") -> float:
        """
        Compute similarity via Rust multi-gate matching.

        Returns 0.0-1.0 where 1.0 is a perfect match.

        This signature-only method is retained for non-economic discovery.
        Native matcher failures are surfaced instead of becoming false zeroes.
        """
        result = _load_v2_matcher()(self.hex, other.hex)
        if not isinstance(result, dict):
            raise RewardGradeMatcherError(
                "v2 matcher returned an invalid result"
            )
        return _similarity_from_v2_result(result)

    def to_dict(self) -> dict:
        return {
            "signature_v2_hex": self.hex,
            "vert_m": self.vert_m,
            "distance_m": self.distance_m,
            "avg_gradient_pct": self.avg_gradient_pct,
            "h3_anchor": hex(self.h3_anchor) if self.h3_anchor else None,
        }
