"""Canonical vault-completion evidence identity.

This hash is the stable identity for one rider effort on one vault. Replay,
live completion writes, activation bundles, and tx-lifecycle reference IDs must
all use this exact byte layout.
"""
from __future__ import annotations

import hashlib
import struct
from typing import Union

from solders.pubkey import Pubkey

COMPLETION_EVIDENCE_DOMAIN = b"BR_VAULT_COMPLETION_V1"
CLIMB_COMPLETION_EVIDENCE_V2_DOMAIN = b"BR_CLIMB_COMPLETION_V2"
RELEASED_CLIMB_COMPLETION_EVIDENCE_V3_DOMAIN = b"BR_RELEASED_CLIMB_COMPLETION_V3"


def normalize_signature_hash(signature: Union[bytes, str]) -> bytes:
    """Return the 32-byte hash of a normalized climb signature."""
    if isinstance(signature, bytes):
        if len(signature) == 32:
            return signature
        return hashlib.sha256(signature).digest()

    normalized = signature[2:] if signature.startswith("0x") else signature
    try:
        signature_bytes = bytes.fromhex(normalized)
    except ValueError:
        signature_bytes = signature.encode("utf-8")
    return hashlib.sha256(signature_bytes).digest()


def build_vault_completion_evidence_hash(
    *,
    wallet: Union[str, Pubkey],
    vault_id: int,
    activity_id: Union[str, bytes],
    completed_at: int,
    time_s: int,
    signature_hash: bytes,
) -> bytes:
    """Build the canonical 32-byte evidence hash for a vault completion."""
    if isinstance(wallet, Pubkey):
        wallet_bytes = bytes(wallet)
    else:
        wallet_bytes = bytes(Pubkey.from_string(wallet))

    if isinstance(activity_id, bytes):
        activity_bytes = activity_id
    else:
        activity_bytes = str(activity_id).encode("utf-8")

    if len(signature_hash) != 32:
        raise ValueError("signature_hash must be exactly 32 bytes")
    if vault_id < 0:
        raise ValueError("vault_id must be non-negative")
    if completed_at <= 0:
        raise ValueError("completed_at must be a positive Unix timestamp")
    if time_s <= 0:
        raise ValueError("time_s must be positive")

    hasher = hashlib.sha256()
    hasher.update(COMPLETION_EVIDENCE_DOMAIN)
    hasher.update(wallet_bytes)
    hasher.update(struct.pack("<Q", vault_id))
    hasher.update(struct.pack("<I", len(activity_bytes)))
    hasher.update(activity_bytes)
    hasher.update(struct.pack("<qI", completed_at, time_s))
    hasher.update(signature_hash)
    return hasher.digest()


def build_climb_completion_evidence_v2(
    *,
    ride_attestation: Union[str, Pubkey],
    vault: Union[str, Pubkey],
    completion_time_s: int,
    cal_tribute: int,
) -> bytes:
    """Build the tribute-bound V2 hash from fields the program can verify."""
    ride_attestation_key = (
        ride_attestation
        if isinstance(ride_attestation, Pubkey)
        else Pubkey.from_string(ride_attestation)
    )
    vault_key = vault if isinstance(vault, Pubkey) else Pubkey.from_string(vault)
    if completion_time_s <= 0 or completion_time_s > 0xFFFF_FFFF:
        raise ValueError("completion_time_s must fit a positive u32")
    if cal_tribute < 0 or cal_tribute > 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("cal_tribute must fit a u64")

    hasher = hashlib.sha256()
    hasher.update(CLIMB_COMPLETION_EVIDENCE_V2_DOMAIN)
    hasher.update(bytes(ride_attestation_key))
    hasher.update(bytes(vault_key))
    hasher.update(struct.pack("<I", completion_time_s))
    hasher.update(struct.pack("<Q", cal_tribute))
    return hasher.digest()


def build_released_climb_completion_evidence_v3(
    *,
    release_authority: Union[str, Pubkey],
    ride_attestation: Union[str, Pubkey],
    vault: Union[str, Pubkey],
    completion_time_s: int,
    cal_tribute: int,
) -> bytes:
    """Build the release-bound V3 hash exactly as the program verifies it."""
    release_key = (
        release_authority
        if isinstance(release_authority, Pubkey)
        else Pubkey.from_string(release_authority)
    )
    ride_key = (
        ride_attestation
        if isinstance(ride_attestation, Pubkey)
        else Pubkey.from_string(ride_attestation)
    )
    vault_key = vault if isinstance(vault, Pubkey) else Pubkey.from_string(vault)
    if completion_time_s <= 0 or completion_time_s > 0xFFFF_FFFF:
        raise ValueError("completion_time_s must fit a positive u32")
    if cal_tribute < 0 or cal_tribute > 0xFFFF_FFFF_FFFF_FFFF:
        raise ValueError("cal_tribute must fit a u64")

    hasher = hashlib.sha256()
    hasher.update(RELEASED_CLIMB_COMPLETION_EVIDENCE_V3_DOMAIN)
    hasher.update(bytes(release_key))
    hasher.update(bytes(ride_key))
    hasher.update(bytes(vault_key))
    hasher.update(struct.pack("<I", completion_time_s))
    hasher.update(struct.pack("<Q", cal_tribute))
    return hasher.digest()
