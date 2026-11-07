from __future__ import annotations

import hashlib
import json
from pathlib import Path

from app.services.canon_vault_activation import (
    CANON_METRIC_PROJECTION_ALGORITHM,
    build_canon_metric_projection,
)


REPO_ROOT = Path(__file__).parents[3]
MANIFEST_PATH = (
    REPO_ROOT
    / "history/canon-runtime-cutover-2026-07-21/"
    "chain-metric-projection-launch-manifest.json"
)
EXPECTED_REPORT_SHA256 = (
    "de67892dc600affd97e0a5158f3a369ca29777b214ecce41be0e47060736bf0e"
)
EXPECTED_LABELS_SHA256 = (
    "77fbdcc691de9d82124f3d848035f103e5433c6ef2bbe3d8bd64782041c4fdd9"
)


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def test_pinned_launch_manifest_projects_all_57_candidates() -> None:
    manifest = json.loads(MANIFEST_PATH.read_text())

    assert manifest["schema"] == "boulderroller.chain-metric-launch-manifest"
    assert manifest["schema_version"] == 1
    assert manifest["projection_algorithm"] == CANON_METRIC_PROJECTION_ALGORITHM
    assert manifest["source"] == {
        "canon_report_sha256": EXPECTED_REPORT_SHA256,
        "review_labels_sha256": EXPECTED_LABELS_SHA256,
        "resolver": (
            "tools/corpus/canon_traversal_replay.py::"
            "resolve_launch_canon_candidates"
        ),
        "resolver_audit": {
            "carried_approve_labels": 44,
            "boundary_ratifications": 15,
            "locked_validated_carries": [
                "Hagys Ford Road North / Hagys Ford Road",
                "Parker Avenue",
            ],
            "pending_approve_labels": [],
            "resolved_candidates": 57,
        },
    }
    candidates = manifest["candidates"]
    assert len(candidates) == 57
    assert len({row["candidate_fingerprint"] for row in candidates}) == 57
    assert len({row["launch_decision_id"] for row in candidates}) == 57
    assert manifest["candidate_manifest_sha256"] == _canonical_sha256(candidates)

    projections = []
    for row in candidates:
        projection = build_canon_metric_projection(**row["registry_metrics"])
        assert row["chain_metric_projection"] == projection
        projections.append(projection)
    assert len(projections) == 57
    assert all(
        projection["algorithm"] == CANON_METRIC_PROJECTION_ALGORITHM
        for projection in projections
    )
