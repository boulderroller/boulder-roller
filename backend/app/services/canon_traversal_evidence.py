"""Lossless, identity-bound evidence handed from ride phase 1 to D11.

The rider-facing map track is deliberately compressed. Canon traversal cannot
consume that projection because five-decimal coordinates and whole-second
timestamps can change exact gate intersections. This module builds a private
JSONB stream directly from the attested parser output and verifies it again on
load before phase 2 uses it.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple
from uuid import UUID

from .sample_time import sample_time_seconds


CANON_TRAVERSAL_EVIDENCE_VERSION = "canon_traversal_evidence_v1"
MAX_CANON_TRAVERSAL_SAMPLES = 250_000
MAX_CANON_TRAVERSAL_JSON_BYTES = 32 * 1024 * 1024
_HASH_RE = re.compile(r"^[0-9a-f]{64}$")
_REQUIRED_SAMPLE_KEYS = {
    "source_index",
    "t",
    "lat",
    "lon",
    "tile_id",
    "elevation_m",
    "power_w",
    "hr_bpm",
    "speed_mps",
    "gps_valid",
}
_STORAGE_FIELDS = (
    "source_index",
    "t",
    "lat",
    "lon",
    "tile_id",
    "elevation_m",
    "power_w",
    "hr_bpm",
    "speed_mps",
    "gps_valid",
)
_STORAGE_NUMERIC_FIELDS = {
    "t",
    "lat",
    "lon",
    "elevation_m",
    "power_w",
    "hr_bpm",
    "speed_mps",
}


class CanonTraversalEvidenceError(RuntimeError):
    """The persisted D11 evidence is missing, malformed, or was changed."""


def _field(source: Any, *names: str) -> Any:
    if isinstance(source, Mapping):
        for name in names:
            if name in source:
                return source.get(name)
        return None
    for name in names:
        if hasattr(source, name):
            return getattr(source, name)
    return None


def _has_coordinate_field(source: Any) -> bool:
    names = ("lat", "latitude", "lon", "longitude", "lng")
    if isinstance(source, Mapping):
        return any(name in source and source.get(name) is not None for name in names)
    return any(hasattr(source, name) and getattr(source, name) is not None for name in names)


def _finite_number(value: Any) -> Optional[float]:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    # PostgreSQL JSONB canonicalizes signed zero. Normalize before hashing so
    # in-process and persisted evidence have one representation.
    return 0.0 if number == 0.0 else number


def _canonical_json(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise CanonTraversalEvidenceError(
            "canon traversal evidence is not JSON-safe"
        ) from exc


def _digest(
    *,
    ride_id: UUID,
    ride_hash_hex: str,
    ride_parser_version: int,
    evidence_version: str,
    storage_samples: Sequence[Sequence[Any]],
) -> str:
    envelope = {
        "ride_id": str(ride_id),
        "ride_hash_hex": ride_hash_hex,
        "ride_parser_version": ride_parser_version,
        "evidence_version": evidence_version,
        "samples": list(storage_samples),
    }
    return hashlib.sha256(_canonical_json(envelope)).hexdigest()


def _validate_identity(
    ride_id: Any,
    ride_hash_hex: Any,
    ride_parser_version: Any,
    evidence_version: Any,
) -> Tuple[UUID, str, int, str]:
    try:
        parsed_ride_id = UUID(str(ride_id))
    except (TypeError, ValueError) as exc:
        raise CanonTraversalEvidenceError("invalid evidence ride id") from exc
    normalized_hash = str(ride_hash_hex or "").lower()
    if not _HASH_RE.fullmatch(normalized_hash):
        raise CanonTraversalEvidenceError("invalid evidence ride hash")
    try:
        parser_version = int(ride_parser_version)
    except (TypeError, ValueError) as exc:
        raise CanonTraversalEvidenceError("invalid evidence parser version") from exc
    if parser_version <= 0:
        raise CanonTraversalEvidenceError("invalid evidence parser version")
    version = str(evidence_version or "")
    if version != CANON_TRAVERSAL_EVIDENCE_VERSION:
        raise CanonTraversalEvidenceError("unsupported canon traversal evidence version")
    return parsed_ride_id, normalized_hash, parser_version, version


def _validate_samples(raw_samples: Any) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(raw_samples, list):
        raise CanonTraversalEvidenceError("invalid canon traversal evidence samples")
    if len(raw_samples) > MAX_CANON_TRAVERSAL_SAMPLES:
        raise CanonTraversalEvidenceError("canon traversal evidence sample limit exceeded")
    normalized: List[Mapping[str, Any]] = []
    previous_source_index = -1
    for raw in raw_samples:
        if not isinstance(raw, Mapping) or not _REQUIRED_SAMPLE_KEYS.issubset(raw):
            raise CanonTraversalEvidenceError("invalid canon traversal evidence sample")
        source_index = raw.get("source_index")
        if (
            not isinstance(source_index, int)
            or isinstance(source_index, bool)
            or source_index <= previous_source_index
        ):
            raise CanonTraversalEvidenceError("invalid evidence source index")
        previous_source_index = source_index
        gps_valid = raw.get("gps_valid")
        if not isinstance(gps_valid, bool):
            raise CanonTraversalEvidenceError("invalid evidence GPS validity")
        for field_name in (
            "t",
            "lat",
            "lon",
            "elevation_m",
            "power_w",
            "hr_bpm",
            "speed_mps",
        ):
            value = raw.get(field_name)
            if value is not None and _finite_number(value) is None:
                raise CanonTraversalEvidenceError(
                    f"invalid evidence sample {field_name}"
                )
        lat = _finite_number(raw.get("lat"))
        lon = _finite_number(raw.get("lon"))
        t_s = _finite_number(raw.get("t"))
        coordinate_valid = (
            lat is not None
            and lon is not None
            and -90.0 <= lat <= 90.0
            and -180.0 <= lon <= 180.0
        )
        if gps_valid != (coordinate_valid and t_s is not None):
            raise CanonTraversalEvidenceError("inconsistent evidence GPS validity")
        tile_id = raw.get("tile_id")
        if gps_valid and (not isinstance(tile_id, str) or not tile_id):
            raise CanonTraversalEvidenceError("valid GPS evidence is missing its H3 cell")
        if not gps_valid and tile_id is not None:
            raise CanonTraversalEvidenceError("invalid GPS evidence has an H3 cell")
        normalized.append(dict(raw))
    # A JSON round trip gives the in-process path the exact scalar shapes that
    # phase 2 receives back from JSONB.
    return tuple(json.loads(_canonical_json(normalized).decode("utf-8")))


def _number_string(value: Any) -> Optional[str]:
    number = _finite_number(value)
    if number is None:
        return None
    return "0" if number == 0.0 else repr(number)


def _encode_storage_samples(
    samples: Sequence[Mapping[str, Any]],
) -> List[List[Any]]:
    encoded: List[List[Any]] = []
    for sample in samples:
        row: List[Any] = []
        for field_name in _STORAGE_FIELDS:
            value = sample.get(field_name)
            row.append(
                _number_string(value)
                if field_name in _STORAGE_NUMERIC_FIELDS
                else value
            )
        encoded.append(row)
    if len(_canonical_json(encoded)) > MAX_CANON_TRAVERSAL_JSON_BYTES:
        raise CanonTraversalEvidenceError("canon traversal evidence byte limit exceeded")
    return encoded


def _decode_storage_samples(raw_samples: Any) -> Tuple[Mapping[str, Any], ...]:
    if not isinstance(raw_samples, list):
        raise CanonTraversalEvidenceError("invalid stored traversal evidence samples")
    if len(raw_samples) > MAX_CANON_TRAVERSAL_SAMPLES:
        raise CanonTraversalEvidenceError("canon traversal evidence sample limit exceeded")
    decoded: List[Dict[str, Any]] = []
    for raw_row in raw_samples:
        if not isinstance(raw_row, list) or len(raw_row) != len(_STORAGE_FIELDS):
            raise CanonTraversalEvidenceError("invalid stored traversal evidence sample")
        sample: Dict[str, Any] = {}
        for field_name, value in zip(_STORAGE_FIELDS, raw_row):
            if field_name in _STORAGE_NUMERIC_FIELDS:
                if value is not None and not isinstance(value, str):
                    raise CanonTraversalEvidenceError(
                        "stored evidence numerics must use canonical strings"
                    )
                numeric = _finite_number(value)
                if value is not None and _number_string(numeric) != value:
                    raise CanonTraversalEvidenceError(
                        "stored evidence numeric is not canonical"
                    )
                sample[field_name] = numeric
            else:
                sample[field_name] = value
        decoded.append(sample)
    samples = _validate_samples(decoded)
    if _encode_storage_samples(samples) != raw_samples:
        raise CanonTraversalEvidenceError("stored traversal evidence is not canonical")
    return samples


def detector_compatible_samples(
    samples: Sequence[Mapping[str, Any]],
) -> List[Dict[str, Any]]:
    """Project exact D11 evidence onto the legacy Rust detector contract.

    PyO3's detector and segment-power paths require Python ``int`` timestamps.
    Exact fractional timestamps remain untouched in the D11 stream; this copy
    intentionally preserves the pre-canon whole-second detector behavior.
    """
    projected: List[Dict[str, Any]] = []
    for sample in samples:
        t_s = _finite_number(sample.get("t"))
        lat = _finite_number(sample.get("lat"))
        lon = _finite_number(sample.get("lon"))
        tile_id = sample.get("tile_id")
        if (
            t_s is None
            or lat is None
            or lon is None
            or not -90.0 <= lat <= 90.0
            or not -180.0 <= lon <= 180.0
            or not tile_id
        ):
            continue
        compatible = dict(sample)
        compatible["t"] = int(t_s)
        compatible["lat"] = lat
        compatible["lon"] = lon
        compatible["tile_id"] = str(tile_id)
        power_w = _finite_number(sample.get("power_w"))
        hr_bpm = _finite_number(sample.get("hr_bpm"))
        compatible["power_w"] = int(power_w) if power_w is not None else None
        compatible["hr_bpm"] = int(hr_bpm) if hr_bpm is not None else None
        projected.append(compatible)
    return projected


@dataclass(frozen=True)
class CanonTraversalEvidence:
    """Verified D11 sample stream bound to one attested ride identity."""

    ride_id: UUID
    ride_hash_hex: str
    ride_parser_version: int
    evidence_version: str
    samples: Tuple[Mapping[str, Any], ...]
    sample_digest: str

    @classmethod
    def build(
        cls,
        *,
        ride_id: UUID,
        ride_hash_hex: str,
        ride_parser_version: int,
        parsed_ride: Any,
        tile_service: Any,
    ) -> "CanonTraversalEvidence":
        identity = _validate_identity(
            ride_id,
            ride_hash_hex,
            ride_parser_version,
            CANON_TRAVERSAL_EVIDENCE_VERSION,
        )
        parsed_ride_id, normalized_hash, parser_version, evidence_version = identity
        base_time = getattr(parsed_ride, "started_at", None)
        samples: List[Dict[str, Any]] = []
        for source_index, record in enumerate(getattr(parsed_ride, "records", []) or []):
            # Records with neither coordinate are sensor-only. A record with
            # just one coordinate is malformed GPS evidence and must remain in
            # the D11 denominator instead of disappearing during projection.
            if not _has_coordinate_field(record):
                continue
            lat = _finite_number(_field(record, "lat", "latitude"))
            lon = _finite_number(_field(record, "lon", "longitude", "lng"))
            t_s = sample_time_seconds(_field(record, "timestamp", "t"), base_time=base_time)
            t_s = _finite_number(t_s)
            coordinate_valid = (
                lat is not None
                and lon is not None
                and -90.0 <= lat <= 90.0
                and -180.0 <= lon <= 180.0
            )
            gps_valid = coordinate_valid and t_s is not None
            tile_id: Optional[str] = None
            if gps_valid:
                try:
                    tile_id = str(tile_service.lat_lng_to_tile(lat, lon, 10))
                except Exception:
                    gps_valid = False
                    tile_id = None
            samples.append(
                {
                    "source_index": source_index,
                    "t": t_s,
                    "lat": lat if lat is not None and -90.0 <= lat <= 90.0 else None,
                    "lon": lon if lon is not None and -180.0 <= lon <= 180.0 else None,
                    "tile_id": tile_id,
                    "elevation_m": _finite_number(
                        _field(record, "elevation_m", "elevation")
                    ),
                    "power_w": _finite_number(_field(record, "power_w", "power")),
                    "hr_bpm": _finite_number(
                        _field(record, "hr_bpm", "heart_rate_bpm", "heart_rate")
                    ),
                    "speed_mps": _finite_number(_field(record, "speed_mps", "speed")),
                    "gps_valid": bool(gps_valid),
                }
            )
        verified_samples = _validate_samples(samples)
        storage_samples = _encode_storage_samples(verified_samples)
        digest = _digest(
            ride_id=parsed_ride_id,
            ride_hash_hex=normalized_hash,
            ride_parser_version=parser_version,
            evidence_version=evidence_version,
            storage_samples=storage_samples,
        )
        return cls(
            ride_id=parsed_ride_id,
            ride_hash_hex=normalized_hash,
            ride_parser_version=parser_version,
            evidence_version=evidence_version,
            samples=verified_samples,
            sample_digest=digest,
        )

    @classmethod
    def from_row(cls, row: Mapping[str, Any]) -> "CanonTraversalEvidence":
        if not isinstance(row, Mapping):
            raise CanonTraversalEvidenceError("invalid canon traversal evidence row")
        ride_id, ride_hash_hex, parser_version, evidence_version = _validate_identity(
            row.get("ride_id"),
            row.get("ride_hash_hex"),
            row.get("ride_parser_version"),
            row.get("evidence_version"),
        )
        storage_samples = row.get("samples")
        samples = _decode_storage_samples(storage_samples)
        sample_count = row.get("sample_count")
        if (
            not isinstance(sample_count, int)
            or isinstance(sample_count, bool)
            or sample_count != len(samples)
        ):
            raise CanonTraversalEvidenceError("evidence sample count mismatch")
        digest = str(row.get("sample_digest") or "").lower()
        if not _HASH_RE.fullmatch(digest):
            raise CanonTraversalEvidenceError("invalid evidence sample digest")
        expected = _digest(
            ride_id=ride_id,
            ride_hash_hex=ride_hash_hex,
            ride_parser_version=parser_version,
            evidence_version=evidence_version,
            storage_samples=storage_samples,
        )
        if digest != expected:
            raise CanonTraversalEvidenceError("evidence sample digest mismatch")
        return cls(
            ride_id=ride_id,
            ride_hash_hex=ride_hash_hex,
            ride_parser_version=parser_version,
            evidence_version=evidence_version,
            samples=samples,
            sample_digest=digest,
        )

    def to_row(self) -> Dict[str, Any]:
        return {
            "ride_id": str(self.ride_id),
            "ride_hash_hex": self.ride_hash_hex,
            "ride_parser_version": self.ride_parser_version,
            "evidence_version": self.evidence_version,
            "sample_count": len(self.samples),
            "sample_digest": self.sample_digest,
            "samples": _encode_storage_samples(self.samples),
        }

    def raw_samples(self) -> List[Dict[str, Any]]:
        return [dict(sample) for sample in self.samples]

    def detector_samples(self) -> List[Dict[str, Any]]:
        return detector_compatible_samples(self.samples)

    def record_points(self, ride_start_time: Optional[datetime]) -> List[Dict[str, Any]]:
        if ride_start_time is None:
            return []
        points: List[Dict[str, Any]] = []
        for sample in self.samples:
            if not sample.get("gps_valid"):
                continue
            t_s = _finite_number(sample.get("t"))
            if t_s is None:
                continue
            points.append(
                {
                    "timestamp": ride_start_time + timedelta(seconds=t_s),
                    "lat": sample.get("lat"),
                    "lon": sample.get("lon"),
                    "elevation_m": sample.get("elevation_m"),
                    "power_w": sample.get("power_w"),
                    "hr_bpm": sample.get("hr_bpm"),
                    "speed_mps": sample.get("speed_mps"),
                }
            )
        return points
