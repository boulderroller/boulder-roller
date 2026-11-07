"""Strict post-publish registration artifact for the V4-B admin CLI."""

from __future__ import annotations

import hashlib
from typing import Any, Mapping
from uuid import UUID

from .canon_commitment import (
    CANON_PROFILE_HASH_ALGORITHM,
    CanonCommitmentError,
    build_canon_commitment,
    canonical_profile_hash_hex,
)
from .canon_vault_activation import (
    CanonVaultActivationError,
    build_canon_metric_projection,
)


ARTIFACT_KIND = "boulderroller.canon-registration"
ARTIFACT_SCHEMA_VERSION = 1


class CanonRegistrationArtifactError(ValueError):
    """A database row cannot authorize an on-chain Climb registration."""


def _uuid(value: object, *, label: str) -> UUID:
    try:
        normalized = UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise CanonRegistrationArtifactError(f"{label} must be a UUID") from exc
    if normalized.int == 0:
        raise CanonRegistrationArtifactError(f"{label} must not be zero")
    return normalized


def build_canon_registration_artifact(row: Mapping[str, Any]) -> dict[str, Any]:
    """Select and verify only the immutable ratified-row fields consumed by CLI."""
    try:
        row_id = _uuid(row["id"], label="registry row id")
        canon_id = _uuid(row["canon_id"], label="canon_id")
        version = int(row["version"])
        status = str(row["status"])
        policy = str(row["record_continuity_policy"])
        name = str(row["display_name"]).strip()
        profile = list(row["canonical_profile"])
        provenance = dict(row["provenance"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CanonRegistrationArtifactError(
            "registration artifact requires a complete post-publish registry row"
        ) from exc
    if status != "ratified":
        raise CanonRegistrationArtifactError("registration artifact row is not ratified")
    if policy != "new_record_board":
        raise CanonRegistrationArtifactError(
            "carry_records_forward is unavailable until exact record migration is proven"
        )
    if not 3 <= len(name.encode("utf-8")) <= 64:
        raise CanonRegistrationArtifactError("registration name cannot fit the Climb account")
    predecessor = row.get("supersedes_climb_id")
    predecessor_id = _uuid(predecessor, label="supersedes_climb_id") if predecessor else None
    if predecessor_id == row_id:
        raise CanonRegistrationArtifactError("a canon row cannot supersede itself")

    try:
        profile_hash = canonical_profile_hash_hex(profile)
        evidence = dict(provenance["canonical_profile_hash"])
        if (
            evidence.get("algorithm") != CANON_PROFILE_HASH_ALGORITHM
            or str(evidence.get("value") or "").lower() != profile_hash
        ):
            raise CanonRegistrationArtifactError(
                "stored canonical profile hash evidence does not match the row"
            )
        commitment = build_canon_commitment(
            canon_id=canon_id,
            version=version,
            profile_hash_hex=profile_hash,
        )
        metric_projection = build_canon_metric_projection(
            length_m=row["length_m"],
            vert_m=row["vert_m"],
            avg_gradient_pct=row["avg_gradient_pct"],
        )
    except CanonRegistrationArtifactError:
        raise
    except (KeyError, TypeError, CanonCommitmentError, CanonVaultActivationError) as exc:
        raise CanonRegistrationArtifactError(
            "registration artifact row cannot fit the exact V4-B encoding"
        ) from exc

    return {
        "artifact": ARTIFACT_KIND,
        "schema_version": ARTIFACT_SCHEMA_VERSION,
        "registry_row": {
            "id": str(row_id),
            "canon_id": str(canon_id),
            "version": version,
            "status": status,
            "supersedes_climb_id": str(predecessor_id) if predecessor_id else None,
            "record_continuity_policy": policy,
            "display_name": name,
            "canonical_profile": profile,
            "length_m": row["length_m"],
            "vert_m": row["vert_m"],
            "avg_gradient_pct": row["avg_gradient_pct"],
            "provenance": {
                "canonical_profile_hash": {
                    "algorithm": CANON_PROFILE_HASH_ALGORITHM,
                    "value": profile_hash,
                }
            },
        },
        "commitment": {
            "layout": "D12",
            "bytes_hex": commitment.hex(),
            "sha256_hex": hashlib.sha256(commitment).hexdigest(),
        },
        "chain_metric_projection": metric_projection,
    }
