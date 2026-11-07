from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.services.canon_registration_artifact import (
    CanonRegistrationArtifactError,
    build_canon_registration_artifact,
)
from app.services.canon_vault_activation import (
    CANON_METRIC_PROJECTION_ALGORITHM,
    CanonVaultActivationError,
    build_canon_metric_projection,
)


ROW_ID = UUID("11111111-1111-1111-1111-111111111111")
CANON_ID = UUID("22222222-2222-2222-2222-222222222222")
PROFILE_HASH = "08aefaf54eadb227fff49b20abbca026a816d16576c19bc9f4e71e643e7c6d63"
PROJECTION_VECTORS = json.loads(
    (
        Path(__file__).parents[3]
        / "protocol/anchor/tests/fixtures/canon_metric_projection_v1.json"
    ).read_text()
)


def _row() -> dict:
    return {
        "id": str(ROW_ID),
        "canon_id": str(CANON_ID),
        "version": 1,
        "status": "ratified",
        "supersedes_climb_id": None,
        "record_continuity_policy": "new_record_board",
        "display_name": "Levering Street",
        "canonical_profile": [
            {"dist_m": 0.0, "elev_m": 12.0},
            {"dist_m": 100.0, "elev_m": 20.0},
        ],
        "length_m": 100.0,
        "vert_m": 8.0,
        "avg_gradient_pct": 8.0,
        "provenance": {
            "canonical_profile_hash": {
                "algorithm": "blake3_canonical_profile_v1",
                "value": PROFILE_HASH,
            }
        },
    }


def test_post_publish_registration_artifact_is_exact_and_self_verifying() -> None:
    artifact = build_canon_registration_artifact(_row())

    assert artifact["artifact"] == "boulderroller.canon-registration"
    assert artifact["schema_version"] == 1
    assert artifact["registry_row"]["id"] == str(ROW_ID)
    assert artifact["registry_row"]["record_continuity_policy"] == "new_record_board"
    assert artifact["commitment"]["bytes_hex"] == (
        "01" + CANON_ID.hex + "0001" + ("00" * 13) + PROFILE_HASH
    )
    assert len(artifact["commitment"]["sha256_hex"]) == 64


def test_registration_artifact_preserves_raw_metrics_and_exposes_projection() -> None:
    row = _row()
    row.update(
        {
            "length_m": 2031.31,
            "vert_m": 87.36,
            "avg_gradient_pct": 4.301,
        }
    )

    artifact = build_canon_registration_artifact(row)

    assert artifact["registry_row"]["length_m"] == 2031.31
    assert artifact["registry_row"]["vert_m"] == 87.36
    assert artifact["registry_row"]["avg_gradient_pct"] == 4.301
    assert artifact["chain_metric_projection"] == {
        "algorithm": CANON_METRIC_PROJECTION_ALGORITHM,
        "vert_decimeters": 874,
        "distance_meters": 2031,
        "avg_gradient_basis_points": 430,
    }


@pytest.mark.parametrize("vector", PROJECTION_VECTORS["valid"], ids=lambda row: row["name"])
def test_shared_chain_metric_projection_vectors(vector: dict) -> None:
    assert PROJECTION_VECTORS["algorithm"] == CANON_METRIC_PROJECTION_ALGORITHM
    projection = build_canon_metric_projection(**vector["registry_metrics"])

    assert projection == {
        "algorithm": CANON_METRIC_PROJECTION_ALGORITHM,
        **vector["projection"],
    }


@pytest.mark.parametrize("vector", PROJECTION_VECTORS["invalid"], ids=lambda row: row["name"])
def test_shared_chain_metric_projection_rejects_invalid_vectors(vector: dict) -> None:
    with pytest.raises(CanonVaultActivationError, match="metrics"):
        build_canon_metric_projection(**vector["registry_metrics"])


def test_registration_artifact_rejects_pre_publish_or_unproven_rows() -> None:
    with pytest.raises(CanonRegistrationArtifactError, match="post-publish"):
        build_canon_registration_artifact(
            {"compiler_run_mode": "applied", "climb": _row()}
        )

    carry = deepcopy(_row())
    carry["record_continuity_policy"] = "carry_records_forward"
    with pytest.raises(CanonRegistrationArtifactError, match="record migration"):
        build_canon_registration_artifact(carry)

    drifted = deepcopy(_row())
    drifted["canonical_profile"][1]["elev_m"] = 21.0
    with pytest.raises(CanonRegistrationArtifactError, match="hash evidence"):
        build_canon_registration_artifact(drifted)
