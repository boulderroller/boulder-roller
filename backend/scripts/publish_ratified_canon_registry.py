#!/usr/bin/env python3
"""Atomically publish the hash-pinned Philadelphia launch canon registry.

Dry-run is the default. Production execution requires the exact committed
candidate-manifest digest and a database URL for the known Supabase project.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, Sequence

import psycopg2


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS_CORPUS = REPO_ROOT / "tools" / "corpus"
sys.path.insert(0, str(REPO_ROOT / "backend"))
sys.path.insert(0, str(TOOLS_CORPUS))

from app.services.canon_climb_publisher import (  # noqa: E402
    DeferredCommitConnection,
    _validated_publish_parts,
    publish_canon_climb_payload_to_db,
)
from app.services.climb_lab import build_canon_climb_publish_payload  # noqa: E402
from canon_traversal_replay import (  # noqa: E402
    EXPECTED_CANON_SHA256,
    EXPECTED_LABELS_SHA256,
    EXPECTED_LAUNCH_CANON_COUNT,
    InputIntegrityError,
    resolve_launch_canon_candidates,
    sha256_file,
)
from export_canon_metric_projection_manifest import (  # noqa: E402
    EXPECTED_RESOLVER_AUDIT,
    build_manifest as build_metric_manifest,
)


EXPECTED_PROJECT_REF = "qzkqjevawthyboymqrle"
EXPECTED_CANDIDATE_MANIFEST_SHA256 = (
    "da93ce9735a7e609248b67d8f7c6d1d4ea53d8f017e8710e1e76aec20cdc9adb"
)
DEFAULT_REVIEW_LABELS = (
    REPO_ROOT / "backend/tests/fixtures/canon_review_labels_2026-07-05.json"
)
DEFAULT_LAUNCH_MANIFEST = (
    REPO_ROOT
    / "history/canon-runtime-cutover-2026-07-21/"
    "chain-metric-projection-launch-manifest.json"
)
DEFAULT_RATIFIED_BY = "Tim ratified and approved 2026-07-27"


class RegistryPublicationError(RuntimeError):
    """The launch registry cannot be published without identity drift."""


@dataclass(frozen=True)
class RegistryPlan:
    report_sha256: str
    review_labels_sha256: str
    candidate_manifest_sha256: str
    resolver_audit: Mapping[str, Any]
    payloads: tuple[dict[str, Any], ...]

    @property
    def candidate_fingerprints(self) -> set[str]:
        return {
            str(payload["climb"]["candidate_fingerprint"])
            for payload in self.payloads
        }

    @property
    def expected_corridor_cells(self) -> dict[str, int]:
        return {
            str(payload["climb"]["candidate_fingerprint"]): len(
                payload["corridor_cells"]
            )
            for payload in self.payloads
        }


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RegistryPublicationError(f"cannot load pinned JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise RegistryPublicationError(f"pinned JSON input is not an object: {path}")
    return value


def build_registry_plan(
    *,
    report_path: Path,
    review_labels_path: Path = DEFAULT_REVIEW_LABELS,
    launch_manifest_path: Path = DEFAULT_LAUNCH_MANIFEST,
    ratified_by: str = DEFAULT_RATIFIED_BY,
    ratified_at: str | None = None,
) -> RegistryPlan:
    """Resolve, pin, and fully validate all 57 publication payloads."""
    report_sha256 = sha256_file(report_path)
    review_labels_sha256 = sha256_file(review_labels_path)
    if report_sha256 != EXPECTED_CANON_SHA256:
        raise RegistryPublicationError(
            f"canon report hash drifted: expected {EXPECTED_CANON_SHA256}, "
            f"got {report_sha256}"
        )
    if review_labels_sha256 != EXPECTED_LABELS_SHA256:
        raise RegistryPublicationError(
            f"review-label hash drifted: expected {EXPECTED_LABELS_SHA256}, "
            f"got {review_labels_sha256}"
        )

    report = _load_json(report_path)
    review_document = _load_json(review_labels_path)
    committed_manifest = _load_json(launch_manifest_path)
    if (report.get("ratified_boundaries") or {}).get("mode") != "applied":
        raise RegistryPublicationError("canon report is not an applied compiler run")

    try:
        selected, resolver_audit = resolve_launch_canon_candidates(
            report,
            review_document,
        )
        rebuilt_manifest = build_metric_manifest(
            report=report,
            review_document=review_document,
            report_sha256=report_sha256,
            review_labels_sha256=review_labels_sha256,
        )
    except InputIntegrityError as exc:
        raise RegistryPublicationError(str(exc)) from exc

    if resolver_audit != EXPECTED_RESOLVER_AUDIT:
        raise RegistryPublicationError(
            f"launch resolver audit drifted: {resolver_audit!r}"
        )
    if rebuilt_manifest != committed_manifest:
        raise RegistryPublicationError(
            "rebuilt launch metric manifest differs from the committed authority"
        )
    if (
        committed_manifest.get("candidate_manifest_sha256")
        != EXPECTED_CANDIDATE_MANIFEST_SHA256
    ):
        raise RegistryPublicationError("candidate-manifest digest drifted")
    if len(selected) != EXPECTED_LAUNCH_CANON_COUNT:
        raise RegistryPublicationError(
            f"expected {EXPECTED_LAUNCH_CANON_COUNT} launch candidates, "
            f"got {len(selected)}"
        )

    reviewed_at = ratified_at or datetime.now(timezone.utc).isoformat()
    payloads: list[dict[str, Any]] = []
    for candidate in selected:
        enriched = dict(candidate)
        enriched["compiler_run_mode"] = "applied"
        provenance = dict(enriched.get("provenance") or {})
        provenance["launch_ratification"] = {
            "authority": str(enriched["_launch_authority"]),
            "decision_id": str(enriched["_launch_decision_id"]),
            "candidate_manifest_sha256": EXPECTED_CANDIDATE_MANIFEST_SHA256,
            "canon_report_sha256": report_sha256,
            "review_labels_sha256": review_labels_sha256,
        }
        enriched["provenance"] = provenance
        payload = build_canon_climb_publish_payload(
            enriched,
            ratified_by=ratified_by,
            ratified_at=reviewed_at,
        )
        _validated_publish_parts(payload)
        payloads.append(payload)

    payloads.sort(
        key=lambda payload: str(payload["climb"]["candidate_fingerprint"])
    )
    fingerprints = [
        str(payload["climb"]["candidate_fingerprint"])
        for payload in payloads
    ]
    if len(fingerprints) != len(set(fingerprints)):
        raise RegistryPublicationError("launch publication payloads contain duplicates")

    return RegistryPlan(
        report_sha256=report_sha256,
        review_labels_sha256=review_labels_sha256,
        candidate_manifest_sha256=EXPECTED_CANDIDATE_MANIFEST_SHA256,
        resolver_audit=resolver_audit,
        payloads=tuple(payloads),
    )


def inspect_registry_state(
    connection: Any,
    expected_fingerprints: set[str],
) -> str:
    """Allow only a pristine registry or the exact complete launch set."""
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT candidate_fingerprint, status, version
            FROM public.canon_climbs
            ORDER BY candidate_fingerprint
            """
        )
        rows = list(cursor.fetchall())
    finally:
        cursor.close()
    if not rows:
        return "empty"
    actual_fingerprints = {str(row[0]) for row in rows}
    if (
        len(rows) == len(expected_fingerprints)
        and actual_fingerprints == expected_fingerprints
        and all(str(row[1]) == "ratified" and int(row[2]) == 1 for row in rows)
    ):
        return "exact"
    raise RegistryPublicationError(
        "production canon registry is partial or drifted; refusing mutation"
    )


def verify_registry_rows(
    connection: Any,
    expected_corridor_cells: Mapping[str, int],
) -> dict[str, Any]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT
                cc.candidate_fingerprint,
                cc.id::text,
                cc.canon_id::text,
                cc.status,
                cc.version,
                count(cells.tile_id)::integer AS corridor_cell_count
            FROM public.canon_climbs AS cc
            LEFT JOIN public.canon_corridor_cells AS cells
              ON cells.canon_climb_id = cc.id
            GROUP BY
                cc.candidate_fingerprint,
                cc.id,
                cc.canon_id,
                cc.status,
                cc.version
            ORDER BY cc.candidate_fingerprint
            """
        )
        rows = list(cursor.fetchall())
    finally:
        cursor.close()

    actual = {str(row[0]): row for row in rows}
    if set(actual) != set(expected_corridor_cells):
        raise RegistryPublicationError(
            "published registry fingerprint set does not match the launch manifest"
        )
    if len({str(row[2]) for row in rows}) != len(rows):
        raise RegistryPublicationError("published canon identities are not unique")
    for fingerprint, expected_cells in expected_corridor_cells.items():
        row = actual[fingerprint]
        if (
            str(row[3]) != "ratified"
            or int(row[4]) != 1
            or int(row[5]) != expected_cells
        ):
            raise RegistryPublicationError(
                f"published registry row drifted for {fingerprint}"
            )
    return {
        "ratified_rows": len(rows),
        "unique_canon_ids": len({str(row[2]) for row in rows}),
        "corridor_cells": sum(int(row[5]) for row in rows),
    }


def publish_payloads_atomically(
    payloads: Sequence[dict[str, Any]],
    *,
    connection: Any,
    publish_one: Callable[..., dict[str, Any]] = publish_canon_climb_payload_to_db,
    verify: Callable[[], None],
) -> list[dict[str, Any]]:
    """Run the existing row publisher under one outer all-or-nothing commit."""
    deferred = DeferredCommitConnection(connection)
    results: list[dict[str, Any]] = []
    try:
        for payload in payloads:
            results.append(
                publish_one(
                    payload,
                    connection_factory=lambda: deferred,
                )
            )
        verify()
        connection.commit()
    except BaseException:
        connection.rollback()
        raise
    return results


def _safe_result(
    payload: Mapping[str, Any],
    result: Mapping[str, Any],
) -> dict[str, Any]:
    artifact = dict(result.get("registration_artifact") or {})
    commitment = dict(artifact.get("commitment") or {})
    projection = dict(artifact.get("chain_metric_projection") or {})
    provenance = dict(payload["climb"].get("provenance") or {})
    profile_hash = dict(provenance.get("canonical_profile_hash") or {})
    return {
        "candidate_fingerprint": payload["climb"]["candidate_fingerprint"],
        "display_name": payload["climb"]["display_name"],
        "canon_climb_id": result.get("canon_climb_id"),
        "canon_id": result.get("canon_id"),
        "version": result.get("version"),
        "status": result.get("status"),
        "corridor_cell_count": result.get("corridor_cell_count"),
        "canonical_profile_hash": profile_hash.get("value"),
        "commitment_sha256": commitment.get("sha256_hex"),
        "chain_metric_projection": projection,
    }


def _connect(database_url: str) -> Any:
    if EXPECTED_PROJECT_REF not in database_url:
        raise RegistryPublicationError(
            f"DATABASE_URL does not identify expected project {EXPECTED_PROJECT_REF}"
        )
    return psycopg2.connect(
        database_url,
        connect_timeout=15,
        application_name="boulderroller-canon-registry-publisher",
    )


def execute_registry_publication(
    plan: RegistryPlan,
    *,
    database_url: str,
) -> dict[str, Any]:
    expected_cells = plan.expected_corridor_cells
    connection = _connect(database_url)
    results: list[dict[str, Any]] = []
    try:
        before_state = inspect_registry_state(
            connection,
            plan.candidate_fingerprints,
        )
        if before_state == "empty":
            results = publish_payloads_atomically(
                plan.payloads,
                connection=connection,
                verify=lambda: verify_registry_rows(connection, expected_cells),
            )
        else:
            connection.rollback()
    finally:
        connection.close()

    verification_connection = _connect(database_url)
    try:
        verification = verify_registry_rows(
            verification_connection,
            expected_cells,
        )
        verification_connection.rollback()
    finally:
        verification_connection.close()

    return {
        "before_state": before_state,
        "after_state": "exact",
        "verification": verification,
        "published": [
            _safe_result(payload, result)
            for payload, result in zip(plan.payloads, results)
        ],
        "already_exact": before_state == "exact",
    }


def _summary(plan: RegistryPlan) -> dict[str, Any]:
    return {
        "report_sha256": plan.report_sha256,
        "review_labels_sha256": plan.review_labels_sha256,
        "candidate_manifest_sha256": plan.candidate_manifest_sha256,
        "resolver_audit": plan.resolver_audit,
        "candidate_count": len(plan.payloads),
        "corridor_cell_count": sum(plan.expected_corridor_cells.values()),
        "first_fingerprint": min(plan.candidate_fingerprints),
        "last_fingerprint": max(plan.candidate_fingerprints),
    }


def _write_output(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument(
        "--review-labels",
        type=Path,
        default=DEFAULT_REVIEW_LABELS,
    )
    parser.add_argument(
        "--launch-manifest",
        type=Path,
        default=DEFAULT_LAUNCH_MANIFEST,
    )
    parser.add_argument("--ratified-by", default=DEFAULT_RATIFIED_BY)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--confirm-manifest-sha256")
    args = parser.parse_args(list(argv) if argv is not None else None)

    plan = build_registry_plan(
        report_path=args.report,
        review_labels_path=args.review_labels,
        launch_manifest_path=args.launch_manifest,
        ratified_by=args.ratified_by,
    )
    output: dict[str, Any] = {
        "schema": "boulderroller.canon-registry-publication",
        "schema_version": 1,
        "mode": "dry_run",
        "plan": _summary(plan),
    }
    if args.execute:
        if args.confirm_manifest_sha256 != EXPECTED_CANDIDATE_MANIFEST_SHA256:
            raise RegistryPublicationError(
                "--execute requires the exact candidate-manifest confirmation"
            )
        database_url = os.getenv("DATABASE_URL", "")
        if not database_url:
            raise RegistryPublicationError(
                "--execute requires DATABASE_URL in the environment"
            )
        output["mode"] = "executed"
        output["database"] = execute_registry_publication(
            plan,
            database_url=database_url,
        )
    if args.output:
        _write_output(args.output, output)
    print(json.dumps(output, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RegistryPublicationError as exc:
        print(str(exc), file=sys.stderr)
        raise SystemExit(1)
