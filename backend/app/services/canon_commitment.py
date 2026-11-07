"""Exact D12 canon commitment codec shared by registry and runtime paths."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Iterable, Mapping, Union
from uuid import UUID

from blake3 import blake3


CANON_COMMITMENT_PREFIX = 0x01
CANON_COMMITMENT_LENGTH = 64
CANON_COMMITMENT_RESERVED_LENGTH = 13
CANON_PROFILE_HASH_ALGORITHM = "blake3_canonical_profile_v1"
CANON_PROFILE_HASH_DOMAIN = b"boulderroller-canon-profile-v1"
_HEX_32_RE = re.compile(r"[0-9a-f]{64}")


class CanonCommitmentError(ValueError):
    """The supplied bytes or registry identity are not canonical D12 data."""


@dataclass(frozen=True)
class CanonCommitment:
    canon_id: UUID
    version: int
    profile_hash_hex: str

    @property
    def bytes(self) -> bytes:
        return build_canon_commitment(
            canon_id=self.canon_id,
            version=self.version,
            profile_hash_hex=self.profile_hash_hex,
        )

    @property
    def hex(self) -> str:
        return self.bytes.hex()


def _uuid(value: Union[UUID, str]) -> UUID:
    if isinstance(value, UUID):
        normalized = value
    else:
        try:
            normalized = UUID(str(value))
        except (TypeError, ValueError, AttributeError) as exc:
            raise CanonCommitmentError("canon_id must be a UUID") from exc
    if normalized.int == 0:
        raise CanonCommitmentError("canon_id must not be the zero UUID")
    return normalized


def _version(value: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 0xFFFF:
        raise CanonCommitmentError("canon version must be between 1 and 65535")
    return value


def _profile_hash(value: str) -> str:
    normalized = str(value or "").lower()
    if not _HEX_32_RE.fullmatch(normalized):
        raise CanonCommitmentError("canonical profile hash must be 32-byte lowercase hex")
    if normalized == "0" * 64:
        raise CanonCommitmentError("canonical profile hash must not be all zero")
    return normalized


def canonical_profile_hash_hex(profile: Iterable[Mapping[str, object]]) -> str:
    """Hash normalized profile samples with the registry's frozen v1 domain."""
    hasher = blake3(CANON_PROFILE_HASH_DOMAIN)
    count = 0
    previous_distance: float | None = None
    for point in profile:
        if not isinstance(point, Mapping):
            raise CanonCommitmentError("canonical profile samples must be mappings")
        try:
            distance = float(point["dist_m"])
            elevation = float(point["elev_m"])
        except (KeyError, TypeError, ValueError, OverflowError) as exc:
            raise CanonCommitmentError("canonical profile sample is invalid") from exc
        if not math.isfinite(distance) or not math.isfinite(elevation):
            raise CanonCommitmentError("canonical profile values must be finite")
        if previous_distance is not None and distance < previous_distance:
            raise CanonCommitmentError("canonical profile distances are not ordered")
        previous_distance = distance
        hasher.update(f"{distance:.2f}:{elevation:.2f};".encode("utf-8"))
        count += 1
    if count < 2:
        raise CanonCommitmentError("canonical profile requires at least two samples")
    return hasher.hexdigest()


def build_canon_commitment(
    *,
    canon_id: Union[UUID, str],
    version: int,
    profile_hash_hex: str,
) -> bytes:
    """Build the exact 64-byte D12 commitment."""
    normalized_id = _uuid(canon_id)
    normalized_version = _version(version)
    normalized_hash = _profile_hash(profile_hash_hex)
    commitment = b"".join(
        (
            bytes((CANON_COMMITMENT_PREFIX,)),
            normalized_id.bytes,
            normalized_version.to_bytes(2, "big"),
            bytes(CANON_COMMITMENT_RESERVED_LENGTH),
            bytes.fromhex(normalized_hash),
        )
    )
    if len(commitment) != CANON_COMMITMENT_LENGTH:  # pragma: no cover - layout invariant
        raise AssertionError("D12 commitment layout drifted")
    return commitment


def parse_canon_commitment(value: Union[bytes, bytearray, memoryview, str]) -> CanonCommitment:
    """Parse D12 bytes and reject every noncanonical representation."""
    if isinstance(value, str):
        try:
            raw = bytes.fromhex(value)
        except ValueError as exc:
            raise CanonCommitmentError("canon commitment must be hexadecimal") from exc
    else:
        raw = bytes(value)
    if len(raw) != CANON_COMMITMENT_LENGTH:
        raise CanonCommitmentError("canon commitment must be exactly 64 bytes")
    if raw[0] != CANON_COMMITMENT_PREFIX:
        raise CanonCommitmentError("canon commitment prefix is invalid")
    if any(raw[19:32]):
        raise CanonCommitmentError("canon commitment reserved bytes must be zero")
    version = int.from_bytes(raw[17:19], "big")
    _version(version)
    return CanonCommitment(
        canon_id=_uuid(UUID(bytes=raw[1:17])),
        version=version,
        profile_hash_hex=_profile_hash(raw[32:64].hex()),
    )
