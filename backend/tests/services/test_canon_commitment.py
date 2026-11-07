from __future__ import annotations

from uuid import UUID

import pytest

from app.services.canon_commitment import (
    CANON_COMMITMENT_LENGTH,
    CanonCommitmentError,
    build_canon_commitment,
    canonical_profile_hash_hex,
    parse_canon_commitment,
)


CANON_ID = UUID("12345678-1234-5678-90ab-cdef12345678")
PROFILE_HASH = "ab" * 32
EXPECTED_HEX = (
    "01"
    "123456781234567890abcdef12345678"
    "0002"
    + ("00" * 13)
    + PROFILE_HASH
)


def test_d12_commitment_matches_the_frozen_64_byte_layout() -> None:
    commitment = build_canon_commitment(
        canon_id=CANON_ID,
        version=2,
        profile_hash_hex=PROFILE_HASH,
    )

    assert len(commitment) == CANON_COMMITMENT_LENGTH == 64
    assert commitment.hex() == EXPECTED_HEX
    parsed = parse_canon_commitment(commitment)
    assert parsed.canon_id == CANON_ID
    assert parsed.version == 2
    assert parsed.profile_hash_hex == PROFILE_HASH


@pytest.mark.parametrize("version", [0, -1, 65_536, True])
def test_d12_commitment_rejects_versions_outside_unsigned_u16(version: object) -> None:
    with pytest.raises(CanonCommitmentError, match="version"):
        build_canon_commitment(
            canon_id=CANON_ID,
            version=version,  # type: ignore[arg-type]
            profile_hash_hex=PROFILE_HASH,
        )


@pytest.mark.parametrize(
    ("canon_id", "profile_hash", "message"),
    [
        (UUID(int=0), PROFILE_HASH, "canon_id"),
        (CANON_ID, "00" * 32, "profile hash"),
    ],
)
def test_d12_commitment_rejects_zero_identity_components(
    canon_id: UUID,
    profile_hash: str,
    message: str,
) -> None:
    with pytest.raises(CanonCommitmentError, match=message):
        build_canon_commitment(
            canon_id=canon_id,
            version=2,
            profile_hash_hex=profile_hash,
        )


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value[:-1], "64 bytes"),
        (lambda value: bytes([2]) + value[1:], "prefix"),
        (lambda value: value[:19] + b"\x01" + value[20:], "reserved"),
        (lambda value: value[:17] + b"\x00\x00" + value[19:], "version"),
    ],
)
def test_d12_parser_rejects_noncanonical_bytes(mutator, message: str) -> None:
    canonical = bytes.fromhex(EXPECTED_HEX)
    with pytest.raises(CanonCommitmentError, match=message):
        parse_canon_commitment(mutator(canonical))


@pytest.mark.parametrize(
    ("mutator", "message"),
    [
        (lambda value: value[:1] + (b"\x00" * 16) + value[17:], "canon_id"),
        (lambda value: value[:32] + (b"\x00" * 32), "profile hash"),
    ],
)
def test_d12_parser_rejects_zero_identity_components(mutator, message: str) -> None:
    with pytest.raises(CanonCommitmentError, match=message):
        parse_canon_commitment(mutator(bytes.fromhex(EXPECTED_HEX)))


def test_profile_hash_uses_the_registry_canonicalization_domain() -> None:
    profile = (
        {"dist_m": 0.0, "elev_m": 100.0},
        {"dist_m": 12.345, "elev_m": 101.234},
    )

    assert canonical_profile_hash_hex(profile) == (
        "8b0b5e33a5d495b913a979b2c33a948f"
        "baca731fe067bb219e855facf5662600"
    )
