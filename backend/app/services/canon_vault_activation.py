"""Fail-closed V4-B registry and activation-reservation boundary."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Mapping
from uuid import UUID

from ..generated_program_version import CURRENT_PROGRAM_VERSION, PROGRAM_VERSION_FAMILY
from .canon_commitment import (
    CANON_PROFILE_HASH_ALGORITHM,
    CanonCommitmentError,
    build_canon_commitment,
    canonical_profile_hash_hex,
)


# V4-B ABI changes are append-only (check_program_version.py), so the canon
# instructions first shipped at 0x4B stay valid in every later V4-B patch.
CANON_RUNTIME_MIN_PROGRAM_VERSION = 0x4B
CANON_RUNTIME_PROGRAM_FAMILY = "V4-B"
CANON_LENGTH_SCALE = 1
CANON_VERT_SCALE = 10
CANON_GRADIENT_SCALE = 100
CANON_METRIC_PROJECTION_ALGORITHM = "boulderroller_chain_metric_projection_v1"


class CanonVaultActivationError(RuntimeError):
    """Canonical Climb activation cannot safely proceed."""


@dataclass(frozen=True)
class CanonVaultSource:
    climb_id: UUID
    canon_id: UUID
    version: int
    commitment_hex: str
    commitment_hash_hex: str
    profile_hash_hex: str
    climb_pda: str
    name: str
    vert_m: float
    distance_m: int
    avg_gradient_pct: float

    @property
    def vert_m_fixed(self) -> int:
        return encode_canon_metric(
            self.vert_m,
            scale=CANON_VERT_SCALE,
            minimum=1,
            maximum=0xFFFFFFFF,
            require_exact_encoding=True,
        )[1]

    @property
    def avg_gradient_pct_fixed(self) -> int:
        return encode_canon_metric(
            self.avg_gradient_pct,
            scale=CANON_GRADIENT_SCALE,
            minimum=0,
            maximum=0xFFFF,
            require_exact_encoding=True,
        )[1]


def require_canon_runtime_program(*, program_version: int, family: str) -> None:
    if (
        isinstance(program_version, bool)
        or not isinstance(program_version, int)
        or program_version < CANON_RUNTIME_MIN_PROGRAM_VERSION
        or program_version > 0xFF
        or family != CANON_RUNTIME_PROGRAM_FAMILY
    ):
        raise CanonVaultActivationError(
            "canonical Vault creation requires the exact V4-B program family"
        )


def require_generated_canon_runtime_program() -> None:
    require_canon_runtime_program(
        program_version=CURRENT_PROGRAM_VERSION,
        family=PROGRAM_VERSION_FAMILY,
    )


def _one_row(result: Any, *, label: str) -> Mapping[str, Any]:
    rows = list(getattr(result, "data", None) or [])
    if len(rows) != 1:
        raise CanonVaultActivationError(f"exactly one {label} is required")
    return rows[0]


def encode_canon_metric(
    value: object,
    *,
    scale: int,
    minimum: int,
    maximum: int,
    require_exact_encoding: bool = False,
) -> tuple[float, int]:
    """Quantize one nonnegative registry metric to its Anchor integer field.

    Registry values retain compiler precision. The V4-B account stores length in
    whole meters, vertical gain in decimeters, and gradient in basis points. At
    those boundaries we round decimal values halfway up, then compare and persist
    only the resulting encoded integer. Chain-derived values can opt into the
    stricter exact-encoding check so an over-precise projection fails closed.
    """
    try:
        decimal = Decimal(str(value))
        scaled = decimal * scale
    except (InvalidOperation, TypeError, ValueError) as exc:
        raise CanonVaultActivationError("ratified Climb metrics are invalid") from exc
    if (
        not decimal.is_finite()
        or not scaled.is_finite()
        or decimal < 0
    ):
        raise CanonVaultActivationError("ratified Climb metrics are invalid")
    encoded_decimal = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    quantized_decimal = encoded_decimal / Decimal(scale)
    if require_exact_encoding and decimal != quantized_decimal:
        raise CanonVaultActivationError("ratified Climb metrics are invalid")
    encoded = int(encoded_decimal)
    if encoded < minimum or encoded > maximum:
        raise CanonVaultActivationError("ratified Climb metrics are invalid")
    return float(quantized_decimal), encoded


def build_canon_metric_projection(
    *,
    length_m: object,
    vert_m: object,
    avg_gradient_pct: object,
) -> dict[str, int | str]:
    """Project precise registry measurements into immutable V4-B integers."""
    _, vert_decimeters = encode_canon_metric(
        vert_m,
        scale=CANON_VERT_SCALE,
        minimum=1,
        maximum=0xFFFFFFFF,
    )
    _, distance_meters = encode_canon_metric(
        length_m,
        scale=CANON_LENGTH_SCALE,
        minimum=1,
        maximum=0xFFFFFFFF,
    )
    _, avg_gradient_basis_points = encode_canon_metric(
        avg_gradient_pct,
        scale=CANON_GRADIENT_SCALE,
        minimum=0,
        maximum=0xFFFF,
    )
    return {
        "algorithm": CANON_METRIC_PROJECTION_ALGORITHM,
        "vert_decimeters": vert_decimeters,
        "distance_meters": distance_meters,
        "avg_gradient_basis_points": avg_gradient_basis_points,
    }


def resolve_canon_vault_source(*, client: Any, climb_id: UUID) -> CanonVaultSource:
    """Resolve one exact ratified registry row and its finalized V4-B Climb."""
    try:
        normalized_climb_id = UUID(str(climb_id))
    except (TypeError, ValueError) as exc:
        raise CanonVaultActivationError("climb_id must identify an exact registry row") from exc

    registry_result = (
        client.from_("canon_climbs")
        .select(
            "id, canon_id, version, status, display_name, canonical_profile, "
            "length_m, vert_m, avg_gradient_pct, provenance, "
            "record_continuity_policy"
        )
        .eq("id", str(normalized_climb_id))
        .eq("status", "ratified")
        .limit(2)
        .execute()
    )
    try:
        registry = _one_row(registry_result, label="current ratified Climb row")
    except CanonVaultActivationError as exc:
        raise CanonVaultActivationError("Climb is not an exact current ratified row") from exc

    try:
        canon_id = UUID(str(registry["canon_id"]))
        version = int(registry["version"])
        provenance = registry.get("provenance") or {}
        profile_evidence = provenance.get("canonical_profile_hash") or {}
        if profile_evidence.get("algorithm") != CANON_PROFILE_HASH_ALGORITHM:
            raise CanonVaultActivationError("canonical profile hash algorithm is invalid")
        stored_profile_hash = str(profile_evidence.get("value") or "").lower()
        computed_profile_hash = canonical_profile_hash_hex(
            registry.get("canonical_profile") or []
        )
        if stored_profile_hash != computed_profile_hash:
            raise CanonVaultActivationError("canonical profile hash does not match registry row")
        commitment = build_canon_commitment(
            canon_id=canon_id,
            version=version,
            profile_hash_hex=stored_profile_hash,
        )
    except CanonVaultActivationError:
        raise
    except (KeyError, TypeError, ValueError, CanonCommitmentError) as exc:
        raise CanonVaultActivationError("ratified Climb commitment is invalid") from exc

    indexed_result = (
        client.from_("indexed_climbs")
        .select(
            "pda, canon_climb_id, canon_commitment_hex, commitment_hash_hex, "
            "canon_id, canon_version, canonical_profile_hash_hex, "
            "successor_climb_pda, record_continuity_policy, quarantined, "
            "vault_pda, name, vert_m, distance_m, avg_gradient_pct"
        )
        .eq("canon_climb_id", str(normalized_climb_id))
        .eq("quarantined", False)
        .limit(2)
        .execute()
    )
    try:
        indexed = _one_row(indexed_result, label="indexed V4-B Climb")
    except CanonVaultActivationError as exc:
        raise CanonVaultActivationError("exact indexed V4-B Climb is unavailable") from exc

    try:
        name = str(registry["display_name"]).strip()
        vert_m, vert_m_fixed = encode_canon_metric(
            registry["vert_m"],
            scale=CANON_VERT_SCALE,
            minimum=1,
            maximum=0xFFFFFFFF,
        )
        _, distance_m = encode_canon_metric(
            registry["length_m"],
            scale=CANON_LENGTH_SCALE,
            minimum=1,
            maximum=0xFFFFFFFF,
        )
        avg_gradient_pct, avg_gradient_pct_fixed = encode_canon_metric(
            registry["avg_gradient_pct"],
            scale=CANON_GRADIENT_SCALE,
            minimum=0,
            maximum=0xFFFF,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CanonVaultActivationError("ratified Climb metrics are invalid") from exc
    if not name or not 3 <= len(name.encode("utf-8")) <= 64:
        raise CanonVaultActivationError("ratified Climb name cannot fit the V4-B account")

    commitment_hex = commitment.hex()
    commitment_hash_hex = hashlib.sha256(commitment).hexdigest()
    indexed_canon_id = indexed.get("canon_id")
    if (
        str(indexed.get("canon_climb_id")) != str(normalized_climb_id)
        or (indexed_canon_id is not None and str(indexed_canon_id) != str(canon_id))
        or int(indexed.get("canon_version") or 0) != version
        or registry.get("record_continuity_policy") != "new_record_board"
        or indexed.get("record_continuity_policy") != "new_record_board"
        or str(indexed.get("successor_climb_pda") or "")
        not in {"", "11111111111111111111111111111111"}
        or str(indexed.get("canon_commitment_hex") or "").lower() != commitment_hex
        or str(indexed.get("canonical_profile_hash_hex") or "").lower()
        != stored_profile_hash
        or (
            indexed.get("commitment_hash_hex") is not None
            and str(indexed.get("commitment_hash_hex")).lower() != commitment_hash_hex
        )
    ):
        raise CanonVaultActivationError(
            "indexed V4-B Climb commitment does not match exact registry row"
        )
    if indexed.get("vault_pda") is not None:
        raise CanonVaultActivationError(
            "indexed V4-B Climb is already attached to a Vault"
        )
    try:
        _, indexed_vert_m_fixed = encode_canon_metric(
            indexed["vert_m"],
            scale=CANON_VERT_SCALE,
            minimum=1,
            maximum=0xFFFFFFFF,
            require_exact_encoding=True,
        )
        _, indexed_distance_m = encode_canon_metric(
            indexed["distance_m"],
            scale=CANON_LENGTH_SCALE,
            minimum=1,
            maximum=0xFFFFFFFF,
            require_exact_encoding=True,
        )
        _, indexed_avg_gradient_pct_fixed = encode_canon_metric(
            indexed["avg_gradient_pct"],
            scale=CANON_GRADIENT_SCALE,
            minimum=0,
            maximum=0xFFFF,
            require_exact_encoding=True,
        )
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise CanonVaultActivationError(
            "indexed V4-B Climb metrics are invalid"
        ) from exc
    if (
        str(indexed.get("name") or "") != name
        or indexed_vert_m_fixed != vert_m_fixed
        or indexed_distance_m != distance_m
        or indexed_avg_gradient_pct_fixed != avg_gradient_pct_fixed
    ):
        raise CanonVaultActivationError(
            "indexed V4-B Climb metrics do not match exact registry row"
        )
    climb_pda = str(indexed.get("pda") or "").strip()
    if not climb_pda:
        raise CanonVaultActivationError("indexed V4-B Climb PDA is unavailable")

    return CanonVaultSource(
        climb_id=normalized_climb_id,
        canon_id=canon_id,
        version=version,
        commitment_hex=commitment_hex,
        commitment_hash_hex=commitment_hash_hex,
        profile_hash_hex=stored_profile_hash,
        climb_pda=climb_pda,
        name=name,
        vert_m=vert_m,
        distance_m=distance_m,
        avg_gradient_pct=avg_gradient_pct,
    )


def reserve_canon_vault_activation(
    *,
    client: Any,
    source: CanonVaultSource,
    creator_wallet: str,
    payment_method: str,
    client_request_id: str,
    vault_id: int,
    vault_pda: str,
    vault_activation_pda: str,
    blockhash: str,
    last_valid_block_height: int,
) -> UUID:
    result = client.rpc(
        "reserve_canon_vault_activation",
        {
            "p_canon_climb_id": str(source.climb_id),
            "p_creator_wallet": creator_wallet,
            "p_payment_method": payment_method,
            "p_client_request_id": client_request_id,
            "p_canon_commitment_hex": source.commitment_hex,
            "p_commitment_hash_hex": source.commitment_hash_hex,
            "p_climb_pda": source.climb_pda,
            "p_vault_id": vault_id,
            "p_vault_pda": vault_pda,
            "p_vault_activation_pda": vault_activation_pda,
            "p_prepared_blockhash": blockhash,
            "p_last_valid_block_height": last_valid_block_height,
        },
    ).execute()
    row = _one_row(result, label="canon Vault activation reservation")
    if row.get("activation_status") != "reserved":
        raise CanonVaultActivationError("canon Vault activation is not reservable")
    return UUID(str(row["preparation_id"]))


def load_canon_vault_release_candidate(
    *, client: Any, vault_id: int
) -> Mapping[str, Any] | None:
    """Load the sole live reservation currently holding one VaultCounter id."""
    if isinstance(vault_id, bool) or vault_id < 0:
        raise CanonVaultActivationError("vault_id must identify one exact reservation")
    result = client.rpc(
        "get_canon_vault_release_candidate",
        {"p_vault_id": vault_id},
    ).execute()
    rows = list(getattr(result, "data", None) or [])
    if not rows:
        return None
    if len(rows) != 1:
        raise CanonVaultActivationError("canon Vault reservation is ambiguous")
    row = rows[0]
    try:
        UUID(str(row["preparation_id"]))
        UUID(str(row["canon_climb_id"]))
        candidate_vault_id = int(row["vault_id"])
        last_valid_block_height = int(row["last_valid_block_height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonVaultActivationError("canon Vault reservation is invalid") from exc
    required_text = (
        "creator_wallet",
        "client_request_id",
        "payment_method",
        "canon_commitment_hex",
        "commitment_hash_hex",
        "climb_pda",
        "vault_pda",
        "vault_activation_pda",
        "prepared_blockhash",
    )
    if (
        candidate_vault_id != vault_id
        or last_valid_block_height <= 0
        or row.get("activation_status") not in {"reserved", "confirmed"}
        or any(not str(row.get(field) or "").strip() for field in required_text)
    ):
        raise CanonVaultActivationError("canon Vault reservation is invalid")
    return row


def load_canon_vault_preparation(
    *, client: Any, preparation_id: UUID, creator_wallet: str
) -> Mapping[str, Any]:
    result = client.rpc(
        "get_canon_vault_preparation",
        {
            "p_preparation_id": str(preparation_id),
            "p_creator_wallet": creator_wallet,
        },
    ).execute()
    return _one_row(result, label="wallet-scoped canon Vault preparation")


def load_canon_climb_runtime_states(
    *, client: Any, climb_ids: list[UUID]
) -> dict[str, str]:
    if len(climb_ids) > 100:
        raise CanonVaultActivationError("canon runtime state query is limited to 100 rows")
    if not climb_ids:
        return {}
    result = client.rpc(
        "get_canon_climb_runtime_states",
        {"p_canon_climb_ids": [str(climb_id) for climb_id in climb_ids]},
    ).execute()
    states: dict[str, str] = {}
    for row in list(getattr(result, "data", None) or []):
        climb_id = str(UUID(str(row["canon_climb_id"])))
        state = str(row.get("runtime_state") or "")
        if state not in {"available", "reserved", "active", "unavailable"}:
            raise CanonVaultActivationError("canon runtime state is invalid")
        if climb_id in states:
            raise CanonVaultActivationError("canon runtime state is ambiguous")
        states[climb_id] = state
    return states


def confirm_canon_vault_activation(
    *,
    client: Any,
    preparation_id: UUID,
    creator_wallet: str,
    tx_signature: str,
    prepared_message_hash: str,
) -> None:
    result = client.rpc(
        "confirm_canon_vault_activation",
        {
            "p_preparation_id": str(preparation_id),
            "p_creator_wallet": creator_wallet,
            "p_tx_signature": tx_signature,
            "p_prepared_message_hash": prepared_message_hash,
        },
    ).execute()
    row = _one_row(result, label="confirmed canon Vault activation")
    if row.get("activation_status") not in {"confirmed", "finalized"}:
        raise CanonVaultActivationError("canon Vault activation did not confirm")


def release_canon_vault_activation_after_absence(
    *,
    client: Any,
    preparation_id: UUID,
    creator_wallet: str,
    observed_finalized_slot: int,
    observed_finalized_block_height: int,
    reason: str,
) -> bool:
    if (
        isinstance(observed_finalized_slot, bool)
        or observed_finalized_slot < 0
        or isinstance(observed_finalized_block_height, bool)
        or observed_finalized_block_height < 0
    ):
        raise CanonVaultActivationError(
            "explicit finalized on-chain absence is required to release reservation"
        )
    result = client.rpc(
        "release_canon_vault_activation",
        {
            "p_preparation_id": str(preparation_id),
            "p_creator_wallet": creator_wallet,
            "p_chain_absence_confirmed": True,
            "p_observed_finalized_slot": observed_finalized_slot,
            "p_observed_finalized_block_height": observed_finalized_block_height,
            "p_reason": reason,
        },
    ).execute()
    return bool(getattr(result, "data", False))
