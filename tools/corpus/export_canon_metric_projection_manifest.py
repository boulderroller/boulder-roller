#!/usr/bin/env python3
"""Export the pinned, privacy-safe launch set for V4-B metric projection."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.canon_vault_activation import (  # noqa: E402
    CANON_METRIC_PROJECTION_ALGORITHM,
    build_canon_metric_projection,
)
from canon_traversal_replay import (  # noqa: E402
    EXPECTED_CANON_SHA256,
    EXPECTED_LABELS_SHA256,
    EXPECTED_LAUNCH_CANON_COUNT,
    InputIntegrityError,
    resolve_launch_canon_candidates,
    sha256_file,
)


MANIFEST_SCHEMA = "boulderroller.chain-metric-launch-manifest"
MANIFEST_SCHEMA_VERSION = 1
EXPECTED_RESOLVER_AUDIT = {
    "carried_approve_labels": 44,
    "boundary_ratifications": 15,
    "locked_validated_carries": [
        "Hagys Ford Road North / Hagys Ford Road",
        "Parker Avenue",
    ],
    "pending_approve_labels": [],
    "resolved_candidates": EXPECTED_LAUNCH_CANON_COUNT,
}


def _canonical_sha256(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_manifest(
    *,
    report: Mapping[str, Any],
    review_document: Mapping[str, Any],
    report_sha256: str,
    review_labels_sha256: str,
) -> dict[str, Any]:
    selected, audit = resolve_launch_canon_candidates(report, review_document)
    if audit != EXPECTED_RESOLVER_AUDIT:
        raise InputIntegrityError(f"launch resolver audit drifted: {audit!r}")

    candidates = []
    for candidate in selected:
        registry_metrics = {
            "length_m": candidate["length_m"],
            "vert_m": candidate["vert_m"],
            "avg_gradient_pct": candidate["avg_gradient_pct"],
        }
        # Generation itself fails closed if any launch candidate is unprojectable.
        chain_metric_projection = build_canon_metric_projection(**registry_metrics)
        candidates.append(
            {
                "launch_decision_id": candidate["_launch_decision_id"],
                "launch_authority": candidate["_launch_authority"],
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "display_name": candidate["display_name"],
                "registry_metrics": registry_metrics,
                "chain_metric_projection": chain_metric_projection,
            }
        )
    candidates.sort(
        key=lambda item: (
            str(item["launch_decision_id"]),
            str(item["candidate_fingerprint"]),
        )
    )
    if len(candidates) != EXPECTED_LAUNCH_CANON_COUNT:
        raise InputIntegrityError("launch metric manifest denominator drifted")

    return {
        "schema": MANIFEST_SCHEMA,
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "projection_algorithm": CANON_METRIC_PROJECTION_ALGORITHM,
        "source": {
            "canon_report_sha256": report_sha256,
            "review_labels_sha256": review_labels_sha256,
            "resolver": (
                "tools/corpus/canon_traversal_replay.py::"
                "resolve_launch_canon_candidates"
            ),
            "resolver_audit": audit,
        },
        "candidate_manifest_sha256": _canonical_sha256(candidates),
        "candidates": candidates,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--review-labels", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    report_sha256 = sha256_file(args.report)
    review_labels_sha256 = sha256_file(args.review_labels)
    if report_sha256 != EXPECTED_CANON_SHA256:
        raise InputIntegrityError("canon report hash does not match the replay gate")
    if review_labels_sha256 != EXPECTED_LABELS_SHA256:
        raise InputIntegrityError("review-label hash does not match the replay gate")

    manifest = build_manifest(
        report=json.loads(args.report.read_text()),
        review_document=json.loads(args.review_labels.read_text()),
        report_sha256=report_sha256,
        review_labels_sha256=review_labels_sha256,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        json.dumps(
            {
                "output": str(args.output),
                "candidates": len(manifest["candidates"]),
                "candidate_manifest_sha256": manifest["candidate_manifest_sha256"],
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
